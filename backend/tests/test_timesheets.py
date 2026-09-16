"""
Tests for Timesheets (Stage 10).

The timesheet workflow is the one that proves the engine generalises, because
it has a shape leave does not:

    DRAFT --Submit--> SUBMITTED --Approve--> APPROVED
                                --Reject---> REJECTED --Revise--> DRAFT

That loop back to the beginning is the interesting part. Revise is the
*author's* action starting from a state that is not the workflow's first one,
which is exactly what the Stage 9 rule - "an owner action leaves the initial
state" - could not express. Several tests below exist to pin that down.

Nothing in the service names a state to make a decision. Editability asks
`is_initial` and ownership asks `is_owner_held`, both metadata.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.metadata import seed
from app.models.business_unit import BusinessUnit
from app.models.employee import Employee
from app.models.timesheet import Timesheet
from app.models.user import User
from app.models.workflow_history import WorkflowHistory
from app.models.workflow_state import WorkflowState
from app.services import attendance_service, timesheet_service
from app.services.timesheet_service import TimesheetError, TimesheetNotVisible
from app.workflows import engine
from app.workflows.exceptions import (
    TransitionNotAuthorized,
    TransitionNotAvailable,
    TransitionNotFound,
)

WORKFLOW = "TIMESHEET_APPROVAL"

_UNIT_PARENT = {s.code: s.parent_code for s in seed.BUSINESS_UNITS}
_EMPLOYEE_NAME = {s.code: f"{s.first_name} {s.last_name}" for s in seed.EMPLOYEES}
_UNIT_NAME = {s.code: s.name for s in seed.BUSINESS_UNITS}


def units_under(unit_code: str) -> set[str]:
    found = {unit_code}
    while True:
        grown = found | {u for u, parent in _UNIT_PARENT.items() if parent in found}
        if grown == found:
            return found
        found = grown


def assert_scoped_to(rows: list[dict], unit_code: str) -> None:
    allowed = {_UNIT_NAME[code] for code in units_under(unit_code)}
    leaked = {r["business_unit"]["name"] for r in rows} - allowed
    assert not leaked, f"rows leaked from outside {unit_code}: {sorted(leaked)}"


def unit(db: Session, code: str) -> BusinessUnit:
    return db.scalar(select(BusinessUnit).where(BusinessUnit.code == code))


_counter = {"n": 0}


def staff(
    db: Session, make_user, username: str, role: str, unit_code: str,
    *, with_employee: bool = True,
) -> User:
    user = make_user(username, (role,))
    user.business_units.append(unit(db, unit_code))
    db.commit()

    if with_employee:
        _counter["n"] += 1
        n = _counter["n"]
        db.add(Employee(
            employee_code=f"EMP-TS{n:03d}",
            user_id=user.id,
            first_name=username.capitalize(),
            last_name="Sheettest",
            email=f"{username}.sheettest{n}@example.local",
            business_unit_id=unit(db, unit_code).id,
        ))
        db.commit()
    return user


def make_entry(
    db: Session, user: User, *, hours: float = 7.5, when: date | None = None,
    description: str = "Test work", reference: str | None = "PRJ-999",
) -> Timesheet:
    """An entry created through the service, so it starts where the workflow says."""
    return timesheet_service.create_timesheet(db, user, {
        "work_date": when or attendance_service.today(),
        "hours": hours,
        "work_description": description,
        "reference": reference,
    })


def history_count(db: Session, entry: Timesheet) -> int:
    return db.scalar(
        select(func.count()).select_from(WorkflowHistory).where(
            WorkflowHistory.entity_type == "timesheets",
            WorkflowHistory.entity_id == entry.id,
        )
    )


def codes(transitions) -> set[str]:
    return {t.code for t in transitions}


def rows_for(client: TestClient, headers, **params) -> list[dict]:
    params.setdefault("page_size", 100)
    response = client.get("/api/timesheets", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


# ===========================================================================
# The workflow is metadata
# ===========================================================================


def test_the_timesheet_workflow_is_rows_not_code(seeded: Session) -> None:
    workflow = engine.get_workflow(seeded, WORKFLOW)

    states = {
        s.code: (s.is_initial, s.is_final, s.is_owner_held)
        for s in engine.get_states(seeded, workflow)
    }
    transitions = {
        t.code: (t.from_state.code, t.to_state.code)
        for t in engine.get_transitions(seeded, workflow)
    }

    assert states == {
        #            initial  final  owner-held
        "DRAFT":     (True,   False, True),
        "SUBMITTED": (False,  False, False),
        "APPROVED":  (False,  True,  False),
        # Rejected is NOT final - something still leaves it - and it is back
        # with its author, which is what makes Revise theirs.
        "REJECTED":  (False,  False, True),
    }
    assert transitions == {
        "SUBMIT": ("DRAFT", "SUBMITTED"),
        "APPROVE": ("SUBMITTED", "APPROVED"),
        "REJECT": ("SUBMITTED", "REJECTED"),
        "REVISE": ("REJECTED", "DRAFT"),
    }


def test_the_engine_was_not_modified_for_timesheets(seeded: Session, make_user) -> None:
    """
    A Timesheet satisfies the engine's four-field contract and nothing else.
    If this passes, the same engine is driving leave and timesheets alike.
    """
    user = staff(seeded, make_user, "contract", "EMPLOYEE", "DEPARTMENT_1")
    entry = make_entry(seeded, user)

    assert entry.__tablename__ == "timesheets"
    assert entry.workflow_id is not None
    assert entry.current_state_id is not None
    # The engine reads it without knowing what it is.
    assert engine.get_current_state(seeded, entry).code == "DRAFT"


# ===========================================================================
# Creating and editing
# ===========================================================================


def test_an_entry_starts_in_the_workflows_initial_state(
    seeded: Session, make_user
) -> None:
    user = staff(seeded, make_user, "starter", "EMPLOYEE", "DEPARTMENT_1")
    entry = make_entry(seeded, user)

    workflow = engine.get_workflow(seeded, WORKFLOW)
    assert entry.current_state_id == engine.get_initial_state(seeded, workflow).id
    assert entry.current_state.is_initial is True


@pytest.mark.parametrize(
    ("hours", "expected_minutes"),
    [(7.5, 450), (0.25, 15), (8, 480), (1.75, 105)],
)
def test_hours_are_stored_as_whole_minutes(
    hours: float, expected_minutes: int
) -> None:
    assert timesheet_service.hours_to_minutes(hours) == expected_minutes


@pytest.mark.parametrize("hours", [0, -1, 0.001, 25])
def test_impossible_durations_are_refused(hours: float) -> None:
    with pytest.raises(TimesheetError):
        timesheet_service.hours_to_minutes(hours)


def test_an_employee_can_record_their_own_work(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "recorder", "EMPLOYEE", "DEPARTMENT_1")

    response = client.post(
        "/api/timesheets",
        headers=login_headers("recorder"),
        json={
            "work_date": attendance_service.today().isoformat(),
            "hours": 7.5,
            "work_description": "Built the thing",
            "reference": "PRJ-1",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["minutes"] == 450
    assert body["hours"] == 7.5
    assert body["state_code"] == "DRAFT"
    assert body["is_editable"] is True
    assert body["employee"]["name"] == "Recorder Sheettest"


def test_an_employee_id_from_the_browser_is_ignored(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "sneaky", "EMPLOYEE", "DEPARTMENT_1")
    victim = seeded.scalar(select(Employee).where(Employee.employee_code == "EMP-006"))

    response = client.post(
        "/api/timesheets",
        headers=login_headers("sneaky"),
        json={
            "work_date": attendance_service.today().isoformat(),
            "hours": 4,
            "work_description": "Not mine",
            "employee_id": victim.id,
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["employee"]["name"] == "Sneaky Sheettest"


def test_a_user_with_no_employee_record_cannot_record_work(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "accountless", "EMPLOYEE", "DEPARTMENT_1",
          with_employee=False)

    response = client.post(
        "/api/timesheets",
        headers=login_headers("accountless"),
        json={
            "work_date": attendance_service.today().isoformat(),
            "hours": 4,
            "work_description": "Anything",
        },
    )
    assert response.status_code == 409
    assert "employee record" in response.json()["detail"]


def test_an_employee_can_edit_their_draft(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "editor", "EMPLOYEE", "DEPARTMENT_1")
    entry = make_entry(seeded, user, hours=4)

    response = client.patch(
        f"/api/timesheets/{entry.id}",
        headers=login_headers("editor"),
        json={"hours": 6.25, "work_description": "Revised description"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["minutes"] == 375
    assert body["work_description"] == "Revised description"


def test_an_employee_cannot_edit_a_submitted_entry(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "hasty", "EMPLOYEE", "DEPARTMENT_1")
    entry = make_entry(seeded, user)
    timesheet_service.execute_transition(seeded, user, entry.id, "SUBMIT", None)

    response = client.patch(
        f"/api/timesheets/{entry.id}",
        headers=login_headers("hasty"),
        json={"hours": 12},
    )

    assert response.status_code == 400
    assert "no longer" in response.json()["detail"]


def test_an_employee_cannot_edit_somebody_elses_draft(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """Even a manager who may see it must not rewrite it."""
    worker = staff(seeded, make_user, "junior", "EMPLOYEE", "DEPARTMENT_1")
    entry = make_entry(seeded, worker)
    staff(seeded, make_user, "boss", "MANAGER", "BRANCH_1")

    response = client.patch(
        f"/api/timesheets/{entry.id}",
        headers=login_headers("boss"),
        json={"hours": 1},
    )
    assert response.status_code == 403


def test_a_client_supplied_state_is_ignored(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """current_state_id and workflow_id are not part of the update schema."""
    user = staff(seeded, make_user, "forger", "EMPLOYEE", "DEPARTMENT_1")
    entry = make_entry(seeded, user)
    approved = seeded.scalar(
        select(WorkflowState).where(
            WorkflowState.workflow_id == entry.workflow_id,
            WorkflowState.code == "APPROVED",
        )
    )

    response = client.patch(
        f"/api/timesheets/{entry.id}",
        headers=login_headers("forger"),
        json={"current_state_id": approved.id, "workflow_id": 1},
    )

    assert response.status_code == 200, response.text
    assert response.json()["state_code"] == "DRAFT"
    seeded.refresh(entry)
    assert entry.current_state_id != approved.id


# ===========================================================================
# The workflow in motion
# ===========================================================================


def test_submit_moves_a_draft_to_submitted(seeded: Session, make_user) -> None:
    user = staff(seeded, make_user, "submitter", "EMPLOYEE", "DEPARTMENT_1")
    entry = make_entry(seeded, user)

    updated = timesheet_service.execute_transition(seeded, user, entry.id, "SUBMIT", None)
    assert updated.current_state.code == "SUBMITTED"


def test_a_manager_can_approve_and_reject(seeded: Session, make_user) -> None:
    manager = staff(seeded, make_user, "decider", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "doer", "EMPLOYEE", "DEPARTMENT_1")

    approved_entry = make_entry(seeded, worker, when=date(2026, 9, 1))
    rejected_entry = make_entry(seeded, worker, when=date(2026, 9, 2))
    for entry in (approved_entry, rejected_entry):
        timesheet_service.execute_transition(seeded, worker, entry.id, "SUBMIT", None)

    a = timesheet_service.execute_transition(
        seeded, manager, approved_entry.id, "APPROVE", "Looks right."
    )
    r = timesheet_service.execute_transition(
        seeded, manager, rejected_entry.id, "REJECT", "Needs more detail."
    )

    assert a.current_state.code == "APPROVED"
    assert a.current_state.is_final is True
    assert r.current_state.code == "REJECTED"
    assert r.current_state.is_final is False   # something still leaves it


def test_the_offered_actions_differ_by_who_is_asking(
    seeded: Session, make_user
) -> None:
    """
    The same record, the same moment, two people - decided by workflow
    metadata plus ownership, with no role name in the deciding code.
    """
    manager = staff(seeded, make_user, "boss2", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "worker2", "EMPLOYEE", "DEPARTMENT_1")
    entry = make_entry(seeded, worker)

    assert codes(timesheet_service.available_transitions(seeded, worker, entry.id)) == {"SUBMIT"}
    assert codes(timesheet_service.available_transitions(seeded, manager, entry.id)) == set()

    timesheet_service.execute_transition(seeded, worker, entry.id, "SUBMIT", None)

    assert codes(timesheet_service.available_transitions(seeded, worker, entry.id)) == set()
    assert codes(
        timesheet_service.available_transitions(seeded, manager, entry.id)
    ) == {"APPROVE", "REJECT"}


def test_a_rejected_entry_comes_back_to_its_author_to_revise(
    seeded: Session, make_user
) -> None:
    """
    **The case Stage 9's rule could not express.**

    Revise starts from REJECTED, which is not the workflow's initial state, so
    inferring ownership from `is_initial` would have handed this action to the
    approver. `is_owner_held` puts it back where it belongs.
    """
    manager = staff(seeded, make_user, "rejecter", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "reviser", "EMPLOYEE", "DEPARTMENT_1")
    entry = make_entry(seeded, worker)
    timesheet_service.execute_transition(seeded, worker, entry.id, "SUBMIT", None)
    timesheet_service.execute_transition(seeded, manager, entry.id, "REJECT", "No.")

    # The author is offered Revise; the manager who rejected it is offered nothing.
    assert codes(timesheet_service.available_transitions(seeded, worker, entry.id)) == {"REVISE"}
    assert codes(timesheet_service.available_transitions(seeded, manager, entry.id)) == set()

    revised = timesheet_service.execute_transition(seeded, worker, entry.id, "REVISE", None)
    assert revised.current_state.code == "DRAFT"


def test_a_rejected_entry_is_not_editable_until_it_is_revised(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """
    Owner-held and editable are two different questions. A rejected entry is
    back on its author's desk, but the workflow has not reopened it for
    changes until they revise it.
    """
    manager = staff(seeded, make_user, "gatekeeper", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "author", "EMPLOYEE", "DEPARTMENT_1")
    entry = make_entry(seeded, worker)
    timesheet_service.execute_transition(seeded, worker, entry.id, "SUBMIT", None)
    timesheet_service.execute_transition(seeded, manager, entry.id, "REJECT", "No.")
    headers = login_headers("author")

    blocked = client.patch(
        f"/api/timesheets/{entry.id}", headers=headers, json={"hours": 2}
    )
    assert blocked.status_code == 400

    client.post(
        f"/api/timesheets/{entry.id}/transition",
        headers=headers, json={"transition_code": "REVISE"},
    )
    allowed = client.patch(
        f"/api/timesheets/{entry.id}", headers=headers, json={"hours": 2}
    )
    assert allowed.status_code == 200
    assert allowed.json()["minutes"] == 120


def test_a_full_round_trip_reaches_approval(seeded: Session, make_user) -> None:
    """Draft, submitted, rejected, revised, resubmitted, approved."""
    manager = staff(seeded, make_user, "roundboss", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "roundworker", "EMPLOYEE", "DEPARTMENT_1")
    entry = make_entry(seeded, worker)

    for actor, code in (
        (worker, "SUBMIT"), (manager, "REJECT"), (worker, "REVISE"),
        (worker, "SUBMIT"), (manager, "APPROVE"),
    ):
        timesheet_service.execute_transition(seeded, actor, entry.id, code, None)

    seeded.refresh(entry)
    assert entry.current_state.code == "APPROVED"
    # Opening entry plus five transitions.
    assert history_count(seeded, entry) == 6


def test_nobody_approves_their_own_work(seeded: Session, make_user) -> None:
    manager = staff(seeded, make_user, "selfish", "MANAGER", "BRANCH_1")
    entry = make_entry(seeded, manager)
    timesheet_service.execute_transition(seeded, manager, entry.id, "SUBMIT", None)

    assert codes(timesheet_service.available_transitions(seeded, manager, entry.id)) == set()
    with pytest.raises(TransitionNotAuthorized):
        timesheet_service.execute_transition(seeded, manager, entry.id, "APPROVE", None)

    seeded.refresh(entry)
    assert entry.current_state.code == "SUBMITTED"


def test_a_transition_the_metadata_does_not_define_is_refused(
    seeded: Session, make_user
) -> None:
    """There is no DRAFT -> APPROVED arrow, so the jump cannot be made."""
    manager = staff(seeded, make_user, "jumper", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "jumped", "EMPLOYEE", "DEPARTMENT_1")
    entry = make_entry(seeded, worker)

    with pytest.raises(TransitionNotAvailable):
        timesheet_service.execute_transition(seeded, manager, entry.id, "APPROVE", None)

    seeded.refresh(entry)
    assert entry.current_state.code == "DRAFT"


def test_an_unknown_transition_code_is_refused(seeded: Session, make_user) -> None:
    manager = staff(seeded, make_user, "inventor", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "invented", "EMPLOYEE", "DEPARTMENT_1")
    entry = make_entry(seeded, worker)
    timesheet_service.execute_transition(seeded, worker, entry.id, "SUBMIT", None)

    with pytest.raises(TransitionNotFound):
        timesheet_service.execute_transition(
            seeded, manager, entry.id, "RUBBER_STAMP", None
        )


def test_an_employee_cannot_approve_a_colleagues_work(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    worker = staff(seeded, make_user, "peer1", "EMPLOYEE", "DEPARTMENT_1")
    entry = make_entry(seeded, worker)
    timesheet_service.execute_transition(seeded, worker, entry.id, "SUBMIT", None)
    staff(seeded, make_user, "peer2", "EMPLOYEE", "DEPARTMENT_1")

    response = client.post(
        f"/api/timesheets/{entry.id}/transition",
        headers=login_headers("peer2"),
        json={"transition_code": "APPROVE"},
    )

    assert response.status_code == 403
    seeded.refresh(entry)
    assert entry.current_state.code == "SUBMITTED"


# ===========================================================================
# History and transaction safety
# ===========================================================================


def test_history_is_written_for_every_successful_transition(
    seeded: Session, make_user
) -> None:
    manager = staff(seeded, make_user, "logger", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "logged", "EMPLOYEE", "DEPARTMENT_1")
    entry = make_entry(seeded, worker)

    assert history_count(seeded, entry) == 1        # the opening entry

    timesheet_service.execute_transition(seeded, worker, entry.id, "SUBMIT", None)
    timesheet_service.execute_transition(seeded, manager, entry.id, "APPROVE", "Fine.")

    entries = engine.get_history(seeded, entry)
    assert [e.to_state.code for e in entries] == ["DRAFT", "SUBMITTED", "APPROVED"]
    assert entries[0].from_state is None and entries[0].transition is None
    assert entries[1].performed_by_user_id == worker.id
    assert entries[2].performed_by_user_id == manager.id
    assert entries[2].comments == "Fine."
    # Generic: a table name and an id, not a foreign key to one business table.
    assert entries[0].entity_type == "timesheets"


def test_a_failed_transition_writes_no_history_and_changes_no_state(
    seeded: Session, make_user
) -> None:
    """The pair that must never come apart."""
    worker = staff(seeded, make_user, "steady", "EMPLOYEE", "DEPARTMENT_1")
    outsider = staff(seeded, make_user, "outsider", "MANAGER", "BRANCH_3")
    entry = make_entry(seeded, worker)
    timesheet_service.execute_transition(seeded, worker, entry.id, "SUBMIT", None)

    before_state = entry.current_state_id
    before_history = history_count(seeded, entry)

    # Refused by the scope check in the service, not only by the route.
    with pytest.raises(TimesheetNotVisible):
        timesheet_service.execute_transition(seeded, outsider, entry.id, "APPROVE", None)

    seeded.refresh(entry)
    assert entry.current_state_id == before_state
    assert history_count(seeded, entry) == before_history


def test_seeded_entries_carry_a_complete_history(seeded: Session) -> None:
    approved_state = seeded.scalar(
        select(WorkflowState)
        .join(WorkflowState.workflow)
        .where(WorkflowState.code == "APPROVED")
        .where(WorkflowState.workflow.has(code=WORKFLOW))
    )
    entry = seeded.scalar(
        select(Timesheet).where(Timesheet.current_state_id == approved_state.id).limit(1)
    )
    assert entry is not None

    entries = engine.get_history(seeded, entry)
    assert [e.to_state.code for e in entries] == ["DRAFT", "SUBMITTED", "APPROVED"]
    assert all(e.performed_by is not None for e in entries)


# ===========================================================================
# Business-unit scope
# ===========================================================================


def test_a_manager_sees_their_unit_and_its_descendants(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "branchboss", "MANAGER", "BRANCH_1", with_employee=False)

    rows = rows_for(client, login_headers("branchboss"))
    names = {r["employee"]["name"] for r in rows}

    assert_scoped_to(rows, "BRANCH_1")
    assert _EMPLOYEE_NAME["EMP-005"] in names
    assert _EMPLOYEE_NAME["EMP-012"] not in names   # Branch 2
    assert _EMPLOYEE_NAME["EMP-019"] not in names   # Company 2


def test_an_employee_sees_only_their_own_entries(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    colleague = staff(seeded, make_user, "colleague", "EMPLOYEE", "DEPARTMENT_1")
    theirs = make_entry(seeded, colleague)
    staff(seeded, make_user, "nosy", "EMPLOYEE", "DEPARTMENT_1")
    headers = login_headers("nosy")

    assert rows_for(client, headers) == []
    assert client.get(f"/api/timesheets/{theirs.id}", headers=headers).status_code == 403


def test_an_out_of_scope_entry_cannot_be_reached_by_id(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    outsider = staff(seeded, make_user, "far", "EMPLOYEE", "DEPARTMENT_5")
    theirs = make_entry(seeded, outsider)
    timesheet_service.execute_transition(seeded, outsider, theirs.id, "SUBMIT", None)
    staff(seeded, make_user, "near", "MANAGER", "BRANCH_1", with_employee=False)
    headers = login_headers("near")

    assert client.get(f"/api/timesheets/{theirs.id}", headers=headers).status_code == 403
    assert client.get(
        f"/api/timesheets/{theirs.id}/history", headers=headers
    ).status_code == 403
    assert client.post(
        f"/api/timesheets/{theirs.id}/transition",
        headers=headers, json={"transition_code": "APPROVE"},
    ).status_code == 403


def test_a_user_with_no_assignment_sees_only_their_own(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = make_user("unplaced", ("MANAGER",))
    seeded.add(Employee(
        employee_code="EMP-TSX", user_id=user.id,
        first_name="Unplaced", last_name="Manager",
        email="unplaced.sheet@example.local",
        business_unit_id=unit(seeded, "DEPARTMENT_1").id,
    ))
    seeded.commit()
    own = make_entry(seeded, user)

    rows = rows_for(client, login_headers("unplaced"))
    assert len(rows) == 1
    assert rows[0]["id"] == own.id


# ===========================================================================
# Filters, RBAC and the dashboard
# ===========================================================================


def test_the_pending_filter_is_derived_from_metadata(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """
    "Awaiting a decision" means past the author and not finished, derived from
    the two flags rather than from the name SUBMITTED.
    """
    staff(seeded, make_user, "queueboss", "MANAGER", "BRANCH_1", with_employee=False)

    rows = rows_for(client, login_headers("queueboss"), pending="true")

    assert len(rows) > 0
    assert {r["state_code"] for r in rows} == {"SUBMITTED"}
    assert all(r["is_final"] is False for r in rows)
    assert all(r["is_editable"] is False for r in rows)


def test_the_mine_filter_narrows_to_the_caller(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    manager = staff(seeded, make_user, "mineboss", "MANAGER", "BRANCH_1")
    own = make_entry(seeded, manager)
    headers = login_headers("mineboss")

    everything = rows_for(client, headers)
    mine = rows_for(client, headers, mine="true")

    assert len(mine) == 1 and mine[0]["id"] == own.id
    assert len(everything) > len(mine)


def test_timesheet_endpoints_need_authentication(
    client: TestClient, seeded: Session
) -> None:
    assert client.get("/api/timesheets").status_code == 401
    assert client.get("/api/timesheets/dashboard").status_code == 401


def test_a_role_without_the_application_is_refused(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "noapp", "APPLICATION_ADMIN", "COMPANY_1")
    headers = login_headers("noapp")

    assert client.get("/api/timesheets", headers=headers).status_code == 403
    assert client.post("/api/timesheets", headers=headers, json={}).status_code == 403


def test_dashboard_totals_agree_with_the_list(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "dashadmin", "SUPER_ADMIN", "HQ", with_employee=False)
    headers = login_headers("dashadmin")

    summary = client.get("/api/timesheets/dashboard", headers=headers).json()
    listed = client.get(
        "/api/timesheets", headers=headers, params={"page_size": 1}
    ).json()

    assert summary["total_entries"] == listed["total"]
    # The four buckets partition the whole.
    assert (
        summary["draft"] + summary["submitted"]
        + summary["approved"] + summary["rejected"]
    ) == summary["total_entries"]
    assert sum(s["value"] for s in summary["by_status"]) == summary["total_entries"]
    assert summary["approved_hours"] <= summary["total_hours"]


def test_a_rejected_entry_is_not_counted_as_a_draft(
    seeded: Session, make_user
) -> None:
    """
    Both states are owner-held, so "draft" has to be the *initial* state
    rather than "owner-held and unfinished" - otherwise a rejection would hide
    behind a reassuring number.
    """
    manager = staff(seeded, make_user, "countboss", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "counted", "EMPLOYEE", "DEPARTMENT_1")
    entry = make_entry(seeded, worker)
    timesheet_service.execute_transition(seeded, worker, entry.id, "SUBMIT", None)
    timesheet_service.execute_transition(seeded, manager, entry.id, "REJECT", "No.")

    summary = timesheet_service.get_dashboard_summary(seeded, worker)

    assert summary["total_entries"] == 1
    assert summary["rejected"] == 1
    assert summary["draft"] == 0
    assert summary["submitted"] == 0


def test_the_dashboard_respects_business_unit_scope(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "d_hq", "SUPER_ADMIN", "HQ", with_employee=False)
    staff(seeded, make_user, "d_br", "MANAGER", "BRANCH_1", with_employee=False)

    hq = client.get("/api/timesheets/dashboard", headers=login_headers("d_hq")).json()
    br = client.get("/api/timesheets/dashboard", headers=login_headers("d_br")).json()

    assert br["total_entries"] < hq["total_entries"]
    assert br["total_hours"] < hq["total_hours"]


def test_an_employees_dashboard_shows_only_their_own(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "solo", "EMPLOYEE", "DEPARTMENT_1")
    make_entry(seeded, user, hours=3, when=attendance_service.today())
    make_entry(seeded, user, hours=5,
               when=attendance_service.today() - timedelta(days=1))

    summary = client.get(
        "/api/timesheets/dashboard", headers=login_headers("solo")
    ).json()

    assert summary["total_entries"] == 2
    assert summary["total_hours"] == 8.0
    assert summary["draft"] == 2


def test_timesheet_widgets_are_served_with_live_scoped_values(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "w_hq", "SUPER_ADMIN", "HQ", with_employee=False)
    staff(seeded, make_user, "w_br", "MANAGER", "BRANCH_1", with_employee=False)

    hq = client.get(
        "/api/access/dashboards/TIMESHEET_SUMMARY/data", headers=login_headers("w_hq")
    )
    br = client.get(
        "/api/access/dashboards/TIMESHEET_SUMMARY/data", headers=login_headers("w_br")
    )
    assert hq.status_code == 200, hq.text
    assert br.status_code == 200, br.text

    hq_data, br_data = hq.json(), br.json()
    assert hq_data["TIMESHEET_TOTAL"]["value"] > br_data["TIMESHEET_TOTAL"]["value"]
    assert set(hq_data["TIMESHEET_HOURS_BY_WEEK"]) == {"categories", "series"}
    assert set(hq_data["TIMESHEET_HOURS_BY_EMPLOYEE"]) == {"categories", "series"}
    assert "series" in hq_data["TIMESHEET_BY_STATUS"]
    assert all(s["value"] > 0 for s in hq_data["TIMESHEET_BY_STATUS"]["series"])
