"""
Tests for the Leave Management System (Stage 9).

Three things are being proven, and the last two matter most:

  1. the leave rules work - durations, validation, drafts,
  2. **the workflow engine is the only way a state changes**, and a state
     change never happens without a history row explaining it,
  3. **every read is scoped**. What you can see is your own leave, plus the
     leave of people inside your business units if you may approve - never
     more.

The seeded fixture data these tests measure against:

    Headquarters  25 requests
      Company 1   21
        Branch 1  13  -> Department 1 (7), Department 2 (6)
        Branch 2       -> Department 3, Department 4
      Company 2    4

Rather than writing those numbers down twice, the expectations below are
computed from the seed definitions themselves, so a change to the fixture data
updates the tests with it instead of breaking them.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.metadata import seed
from app.models.business_unit import BusinessUnit
from app.models.employee import Employee
from app.models.leave_request import LeaveRequest
from app.models.leave_type import LeaveType
from app.models.user import User
from app.models.workflow_history import WorkflowHistory
from app.models.workflow_state import WorkflowState
from app.services import leave_service
from app.services.leave_service import LeaveError, LeaveNoEmployee, LeaveNotVisible
from app.workflows import engine
from app.workflows.exceptions import (
    TransitionNotAuthorized,
    TransitionNotAvailable,
    TransitionNotFound,
)

WORKFLOW = "LEAVE_APPROVAL"


# ---------------------------------------------------------------------------
# Expectations derived from the seed, not copied from it
# ---------------------------------------------------------------------------

_UNIT_PARENT = {s.code: s.parent_code for s in seed.BUSINESS_UNITS}
_EMPLOYEE_UNIT = {s.code: s.business_unit_code for s in seed.EMPLOYEES}
_EMPLOYEE_NAME = {
    s.code: f"{s.first_name} {s.last_name}" for s in seed.EMPLOYEES
}


def units_under(unit_code: str) -> set[str]:
    """A unit and every descendant - the same rule the recursive CTE applies."""
    found = {unit_code}
    while True:
        grown = found | {
            unit for unit, parent in _UNIT_PARENT.items() if parent in found
        }
        if grown == found:
            return found
        found = grown


def seeded_names_under(unit_code: str) -> set[str]:
    """The employee names whose seeded requests should be visible from here."""
    units = units_under(unit_code)
    return {
        _EMPLOYEE_NAME[r.employee_code]
        for r in seed.LEAVE_REQUESTS
        if _EMPLOYEE_UNIT[r.employee_code] in units
    }


def seeded_count_under(unit_code: str) -> int:
    units = units_under(unit_code)
    return sum(
        1
        for r in seed.LEAVE_REQUESTS
        if _EMPLOYEE_UNIT[r.employee_code] in units
    )


_UNIT_NAME = {s.code: s.name for s in seed.BUSINESS_UNITS}


def unit_names_under(unit_code: str) -> set[str]:
    """The *business unit* names a caller scoped here may legitimately see."""
    return {_UNIT_NAME[code] for code in units_under(unit_code)}


def assert_scoped_to(rows: list[dict], unit_code: str) -> None:
    """
    Every visible row belongs to a unit at or below `unit_code`.

    Deliberately structural rather than a fixed expected list. These tests run
    against the developer's real database, where the seeded fixtures are the
    floor and not the ceiling - somebody who has clicked around in the browser
    has extra rows, and that must not turn into a red suite. What can never
    happen, no matter how much real data is present, is a row from outside the
    caller's scope appearing here; that is what is asserted.
    """
    allowed = unit_names_under(unit_code)
    leaked = {r["business_unit"]["name"] for r in rows} - allowed
    assert not leaked, f"rows leaked from outside {unit_code}: {sorted(leaked)}"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def unit(db: Session, code: str) -> BusinessUnit:
    return db.scalar(select(BusinessUnit).where(BusinessUnit.code == code))


def leave_type(db: Session, code: str = "ANNUAL") -> LeaveType:
    return db.scalar(select(LeaveType).where(LeaveType.code == code))


def state(db: Session, code: str) -> WorkflowState:
    workflow = engine.get_workflow(db, WORKFLOW)
    return db.scalar(
        select(WorkflowState).where(
            WorkflowState.workflow_id == workflow.id, WorkflowState.code == code
        )
    )


_counter = {"n": 0}


def staff(
    db: Session,
    make_user,
    username: str,
    role: str,
    unit_code: str,
    *,
    with_employee: bool = True,
) -> User:
    """
    A user with a role (WHAT), a business unit (WHERE) and, usually, an
    employee record (WHOSE leave this is).

    All three are separate on purpose. A user with a role but no employee
    record can approve other people's leave and has none of their own - which
    is exactly the platform admin's position.
    """
    user = make_user(username, (role,))
    user.business_units.append(unit(db, unit_code))
    db.commit()

    if with_employee:
        _counter["n"] += 1
        n = _counter["n"]
        employee = Employee(
            employee_code=f"EMP-LV{n:03d}",
            user_id=user.id,
            first_name=username.capitalize(),
            last_name="Leavetest",
            email=f"{username}.leavetest{n}@example.local",
            business_unit_id=unit(db, unit_code).id,
        )
        db.add(employee)
        db.commit()
    return user


def make_request(
    db: Session,
    user: User,
    *,
    start: str = "2026-12-01",
    end: str = "2026-12-03",
    type_code: str = "ANNUAL",
    reason: str = "Test request",
) -> LeaveRequest:
    """A request created through the service, so it starts where the workflow says."""
    from datetime import date

    return leave_service.create_request(
        db,
        user,
        {
            "leave_type_id": leave_type(db, type_code).id,
            "start_date": date.fromisoformat(start),
            "end_date": date.fromisoformat(end),
            "reason": reason,
        },
    )


def history_count(db: Session, request: LeaveRequest) -> int:
    return db.scalar(
        select(func.count())
        .select_from(WorkflowHistory)
        .where(
            WorkflowHistory.entity_type == "leave_requests",
            WorkflowHistory.entity_id == request.id,
        )
    )


def visible_rows(client: TestClient, headers) -> list[dict]:
    response = client.get(
        "/api/leave/requests", headers=headers, params={"page_size": 100}
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def visible_names(client: TestClient, headers) -> set[str]:
    return {row["employee"]["name"] for row in visible_rows(client, headers)}


# ===========================================================================
# 1-6. The domain model
# ===========================================================================


def test_leave_types_are_seeded_as_rows_not_an_enum(seeded: Session) -> None:
    """A leave type is configuration. Adding one must be an INSERT."""
    codes = {t.code for t in seeded.scalars(select(LeaveType))}
    assert {"ANNUAL", "SICK", "CASUAL", "UNPAID"} <= codes


def test_a_new_leave_type_needs_no_code_change(seeded: Session) -> None:
    new_type = LeaveType(
        code="COMPASSIONATE", name="Compassionate Leave", max_days=5
    )
    seeded.add(new_type)
    seeded.commit()

    assert new_type.id is not None
    assert new_type.is_active is True


def test_leave_type_code_must_be_unique(seeded: Session) -> None:
    from sqlalchemy.exc import IntegrityError

    seeded.add(LeaveType(code="ANNUAL", name="Annual Leave Again"))
    with pytest.raises(IntegrityError):
        seeded.commit()
    seeded.rollback()


def test_leave_request_can_be_created(seeded: Session, make_user) -> None:
    user = staff(seeded, make_user, "creator", "EMPLOYEE", "DEPARTMENT_1")

    request = make_request(seeded, user, start="2026-12-14", end="2026-12-16")

    assert request.id is not None
    assert request.total_days == 3
    assert request.employee.user_id == user.id


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2026-09-14", "2026-09-16", 3),   # the example from the brief
        ("2026-09-14", "2026-09-14", 1),   # a single day is one day, not zero
        ("2026-09-01", "2026-09-30", 30),  # a whole month, both ends included
        ("2026-12-30", "2027-01-02", 4),   # across a year boundary
    ],
)
def test_total_days_counts_calendar_days_inclusively(
    start: str, end: str, expected: int
) -> None:
    from datetime import date

    assert (
        leave_service.calculate_total_days(
            date.fromisoformat(start), date.fromisoformat(end)
        )
        == expected
    )


def test_an_end_date_before_the_start_is_rejected(seeded: Session, make_user) -> None:
    user = staff(seeded, make_user, "backwards", "EMPLOYEE", "DEPARTMENT_1")

    with pytest.raises(LeaveError):
        make_request(seeded, user, start="2026-12-10", end="2026-12-01")


def test_an_inactive_leave_type_is_rejected(seeded: Session, make_user) -> None:
    user = staff(seeded, make_user, "retired", "EMPLOYEE", "DEPARTMENT_1")
    retired = LeaveType(code="SABBATICAL", name="Sabbatical", is_active=False)
    seeded.add(retired)
    seeded.commit()

    from datetime import date

    with pytest.raises(LeaveError):
        leave_service.create_request(
            seeded,
            user,
            {
                "leave_type_id": retired.id,
                "start_date": date(2026, 12, 1),
                "end_date": date(2026, 12, 2),
                "reason": None,
            },
        )


def test_an_unknown_leave_type_is_rejected(seeded: Session, make_user) -> None:
    user = staff(seeded, make_user, "ghost", "EMPLOYEE", "DEPARTMENT_1")
    from datetime import date

    with pytest.raises(LeaveError):
        leave_service.create_request(
            seeded,
            user,
            {
                "leave_type_id": 999_999,
                "start_date": date(2026, 12, 1),
                "end_date": date(2026, 12, 2),
                "reason": None,
            },
        )


# ===========================================================================
# 7-14. Employee self-service
# ===========================================================================


def test_employee_can_create_their_own_request(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "worker", "EMPLOYEE", "DEPARTMENT_1")
    headers = login_headers("worker")

    response = client.post(
        "/api/leave/requests",
        headers=headers,
        json={
            "leave_type_id": leave_type(seeded).id,
            "start_date": "2026-12-14",
            "end_date": "2026-12-16",
            "reason": "Family visit",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["total_days"] == 3
    assert body["state_code"] == "DRAFT"
    assert body["employee"]["name"] == "Worker Leavetest"


def test_an_employee_id_from_the_browser_is_ignored(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """
    The owner is never taken from the request body.

    Someone else's employee id is sent deliberately here. The API must not
    even have a field for it - the request is created for the caller.
    """
    staff(seeded, make_user, "sneaky", "EMPLOYEE", "DEPARTMENT_1")
    victim = seeded.scalar(
        select(Employee).where(Employee.employee_code == "EMP-006")
    )

    response = client.post(
        "/api/leave/requests",
        headers=login_headers("sneaky"),
        json={
            "leave_type_id": leave_type(seeded).id,
            "start_date": "2026-12-14",
            "end_date": "2026-12-16",
            "employee_id": victim.id,
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["employee"]["name"] == "Sneaky Leavetest"


def test_a_user_with_no_employee_record_cannot_raise_leave(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """And no employee record is invented for them on the way past."""
    before = seeded.scalar(select(func.count()).select_from(Employee))
    staff(
        seeded, make_user, "accountless", "EMPLOYEE", "DEPARTMENT_1",
        with_employee=False,
    )

    response = client.post(
        "/api/leave/requests",
        headers=login_headers("accountless"),
        json={
            "leave_type_id": leave_type(seeded).id,
            "start_date": "2026-12-14",
            "end_date": "2026-12-16",
        },
    )

    assert response.status_code == 409
    assert "employee record" in response.json()["detail"]
    assert seeded.scalar(select(func.count()).select_from(Employee)) == before


def test_employee_can_view_their_own_request(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "owner", "EMPLOYEE", "DEPARTMENT_1")
    request = make_request(seeded, user)

    response = client.get(
        f"/api/leave/requests/{request.id}", headers=login_headers("owner")
    )
    assert response.status_code == 200
    assert response.json()["id"] == request.id


def test_employee_cannot_view_an_unrelated_request(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """
    Two colleagues in the *same department*.

    This is the sharpest version of the rule: being in the same business unit
    is not enough, because an EMPLOYEE has no APPROVE permission. Scope alone
    never grants sight of somebody's leave.
    """
    colleague = staff(seeded, make_user, "colleague", "EMPLOYEE", "DEPARTMENT_1")
    theirs = make_request(seeded, colleague)
    staff(seeded, make_user, "nosy", "EMPLOYEE", "DEPARTMENT_1")

    response = client.get(
        f"/api/leave/requests/{theirs.id}", headers=login_headers("nosy")
    )
    assert response.status_code == 403
    assert visible_names(client, login_headers("nosy")) == set()


def test_employee_can_edit_their_draft(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "editor", "EMPLOYEE", "DEPARTMENT_1")
    request = make_request(seeded, user, start="2026-12-01", end="2026-12-03")

    response = client.put(
        f"/api/leave/requests/{request.id}",
        headers=login_headers("editor"),
        json={"start_date": "2026-12-01", "end_date": "2026-12-10"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # The duration is recalculated on the server, not taken from anyone.
    assert body["total_days"] == 10
    assert body["state_code"] == "DRAFT"


def test_a_client_supplied_total_days_is_ignored_on_edit(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "liar", "EMPLOYEE", "DEPARTMENT_1")
    request = make_request(seeded, user, start="2026-12-01", end="2026-12-03")

    response = client.put(
        f"/api/leave/requests/{request.id}",
        headers=login_headers("liar"),
        json={"total_days": 99},
    )

    assert response.status_code == 200, response.text
    assert response.json()["total_days"] == 3


def test_employee_cannot_edit_a_submitted_request(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "hasty", "EMPLOYEE", "DEPARTMENT_1")
    request = make_request(seeded, user)
    leave_service.execute_transition(seeded, user, request.id, "SUBMIT", None)

    response = client.put(
        f"/api/leave/requests/{request.id}",
        headers=login_headers("hasty"),
        json={"end_date": "2026-12-20"},
    )

    assert response.status_code == 400
    assert "no longer be edited" in response.json()["detail"]


def test_employee_cannot_edit_somebody_elses_draft(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """Even a manager who is allowed to *see* it may not rewrite it."""
    worker = staff(seeded, make_user, "junior", "EMPLOYEE", "DEPARTMENT_1")
    theirs = make_request(seeded, worker)
    staff(seeded, make_user, "boss", "MANAGER", "BRANCH_1")

    response = client.put(
        f"/api/leave/requests/{theirs.id}",
        headers=login_headers("boss"),
        json={"end_date": "2026-12-20"},
    )
    assert response.status_code == 403


def test_employee_can_submit_their_own_request(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "submitter", "EMPLOYEE", "DEPARTMENT_1")
    request = make_request(seeded, user)

    response = client.post(
        f"/api/leave/requests/{request.id}/transition",
        headers=login_headers("submitter"),
        json={"transition_code": "SUBMIT"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["state_code"] == "PENDING_APPROVAL"


def test_employee_can_cancel_their_draft(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "canceller", "EMPLOYEE", "DEPARTMENT_1")
    request = make_request(seeded, user)

    response = client.post(
        f"/api/leave/requests/{request.id}/transition",
        headers=login_headers("canceller"),
        json={"transition_code": "CANCEL"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state_code"] == "CANCELLED"
    assert body["is_final"] is True


# ===========================================================================
# 15-26. The workflow
# ===========================================================================


def test_a_new_request_starts_in_the_workflows_initial_state(
    seeded: Session, make_user
) -> None:
    """
    Note what is asserted: not "it is DRAFT", but "it is whatever the metadata
    marks as initial". The service reads the workflow; it does not know the
    name of the first state.
    """
    user = staff(seeded, make_user, "starter", "EMPLOYEE", "DEPARTMENT_1")
    request = make_request(seeded, user)

    workflow = engine.get_workflow(seeded, WORKFLOW)
    assert request.current_state_id == engine.get_initial_state(seeded, workflow).id
    assert request.current_state.is_initial is True
    assert request.current_state.code == "DRAFT"


def test_the_leave_workflow_is_metadata_not_code(seeded: Session) -> None:
    """The five states and four transitions are rows, and can be read back."""
    workflow = engine.get_workflow(seeded, WORKFLOW)

    states = {s.code for s in engine.get_states(seeded, workflow)}
    transitions = {
        t.code: (t.from_state.code, t.to_state.code)
        for t in engine.get_transitions(seeded, workflow)
    }

    assert states == {
        "DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "CANCELLED"
    }
    assert transitions == {
        "SUBMIT": ("DRAFT", "PENDING_APPROVAL"),
        "CANCEL": ("DRAFT", "CANCELLED"),
        "APPROVE": ("PENDING_APPROVAL", "APPROVED"),
        "REJECT": ("PENDING_APPROVAL", "REJECTED"),
    }


def test_submit_moves_draft_to_pending_approval(seeded: Session, make_user) -> None:
    user = staff(seeded, make_user, "mover", "EMPLOYEE", "DEPARTMENT_1")
    request = make_request(seeded, user)

    updated = leave_service.execute_transition(seeded, user, request.id, "SUBMIT", None)
    assert updated.current_state.code == "PENDING_APPROVAL"


def test_a_transition_the_metadata_does_not_define_is_refused(
    seeded: Session, make_user
) -> None:
    """There is no DRAFT -> APPROVED arrow, so the jump cannot be made."""
    manager = staff(seeded, make_user, "jumper", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "jumped", "EMPLOYEE", "DEPARTMENT_1")
    request = make_request(seeded, worker)

    with pytest.raises(TransitionNotAvailable):
        leave_service.execute_transition(seeded, manager, request.id, "APPROVE", None)

    seeded.refresh(request)
    assert request.current_state.code == "DRAFT"


def test_an_unknown_transition_code_is_refused(seeded: Session, make_user) -> None:
    manager = staff(seeded, make_user, "inventor", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "invented", "EMPLOYEE", "DEPARTMENT_1")
    request = make_request(seeded, worker)
    leave_service.execute_transition(seeded, worker, request.id, "SUBMIT", None)

    with pytest.raises(TransitionNotFound):
        leave_service.execute_transition(
            seeded, manager, request.id, "RUBBER_STAMP", None
        )


def test_an_employee_cannot_approve_somebody_elses_request(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    worker = staff(seeded, make_user, "peer1", "EMPLOYEE", "DEPARTMENT_1")
    request = make_request(seeded, worker)
    leave_service.execute_transition(seeded, worker, request.id, "SUBMIT", None)
    staff(seeded, make_user, "peer2", "EMPLOYEE", "DEPARTMENT_1")

    response = client.post(
        f"/api/leave/requests/{request.id}/transition",
        headers=login_headers("peer2"),
        json={"transition_code": "APPROVE"},
    )

    # They cannot even see it, which is the first wall; the role check is the
    # second. Either way the answer is no and the state is untouched.
    assert response.status_code == 403
    seeded.refresh(request)
    assert request.current_state.code == "PENDING_APPROVAL"


def test_nobody_approves_their_own_leave(seeded: Session, make_user) -> None:
    """
    A manager with every approving role still cannot approve their own
    request, because the action starts after the initial state and they are
    the owner.
    """
    manager = staff(seeded, make_user, "selfish", "MANAGER", "BRANCH_1")
    request = make_request(seeded, manager)
    leave_service.execute_transition(seeded, manager, request.id, "SUBMIT", None)

    offered = {
        t.code for t in leave_service.available_transitions(seeded, manager, request.id)
    }
    assert offered == set()

    with pytest.raises(TransitionNotAuthorized):
        leave_service.execute_transition(seeded, manager, request.id, "APPROVE", None)

    seeded.refresh(request)
    assert request.current_state.code == "PENDING_APPROVAL"


def test_an_authorized_manager_can_approve(seeded: Session, make_user) -> None:
    manager = staff(seeded, make_user, "approver", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "applicant", "EMPLOYEE", "DEPARTMENT_1")
    request = make_request(seeded, worker)
    leave_service.execute_transition(seeded, worker, request.id, "SUBMIT", None)

    updated = leave_service.execute_transition(
        seeded, manager, request.id, "APPROVE", "Cover arranged."
    )

    assert updated.current_state.code == "APPROVED"
    assert updated.current_state.is_final is True


def test_an_authorized_manager_can_reject(seeded: Session, make_user) -> None:
    manager = staff(seeded, make_user, "refuser", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "refused", "EMPLOYEE", "DEPARTMENT_1")
    request = make_request(seeded, worker)
    leave_service.execute_transition(seeded, worker, request.id, "SUBMIT", None)

    updated = leave_service.execute_transition(
        seeded, manager, request.id, "REJECT", "Too many people away."
    )

    assert updated.current_state.code == "REJECTED"
    assert updated.current_state.is_final is True


def test_the_offered_actions_differ_by_who_is_asking(
    seeded: Session, make_user
) -> None:
    """
    The same record, the same moment, two people - and no role name anywhere
    in the code that decides this. It is the workflow metadata plus ownership.
    """
    manager = staff(seeded, make_user, "decider", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "asker", "EMPLOYEE", "DEPARTMENT_1")
    request = make_request(seeded, worker)

    assert {
        t.code for t in leave_service.available_transitions(seeded, worker, request.id)
    } == {"SUBMIT", "CANCEL"}
    assert {
        t.code for t in leave_service.available_transitions(seeded, manager, request.id)
    } == set()

    leave_service.execute_transition(seeded, worker, request.id, "SUBMIT", None)

    assert {
        t.code for t in leave_service.available_transitions(seeded, worker, request.id)
    } == set()
    assert {
        t.code for t in leave_service.available_transitions(seeded, manager, request.id)
    } == {"APPROVE", "REJECT"}


def test_history_is_written_for_a_successful_transition(
    seeded: Session, make_user
) -> None:
    manager = staff(seeded, make_user, "logger", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "logged", "EMPLOYEE", "DEPARTMENT_1")
    request = make_request(seeded, worker)

    # The opening entry is written with the record itself.
    assert history_count(seeded, request) == 1

    leave_service.execute_transition(seeded, worker, request.id, "SUBMIT", None)
    leave_service.execute_transition(seeded, manager, request.id, "APPROVE", "Fine.")

    entries = engine.get_history(seeded, request)
    assert len(entries) == 3
    assert [e.to_state.code for e in entries] == [
        "DRAFT", "PENDING_APPROVAL", "APPROVED"
    ]
    assert entries[0].from_state is None and entries[0].transition is None
    assert entries[1].performed_by_user_id == worker.id
    assert entries[2].performed_by_user_id == manager.id
    assert entries[2].comments == "Fine."
    # Generic, not a foreign key to one business table.
    assert entries[0].entity_type == "leave_requests"


def test_a_failed_transition_writes_no_history_and_changes_no_state(
    seeded: Session, make_user
) -> None:
    """
    The pair that must never come apart.

    A refused action has to leave both halves alone: the state where it was,
    and the trail with no entry claiming otherwise.
    """
    worker = staff(seeded, make_user, "steady", "EMPLOYEE", "DEPARTMENT_1")
    outsider = staff(seeded, make_user, "outsider", "MANAGER", "BRANCH_3")
    request = make_request(seeded, worker)
    leave_service.execute_transition(seeded, worker, request.id, "SUBMIT", None)

    before_state = request.current_state_id
    before_history = history_count(seeded, request)

    # LeaveNotVisible, because the scope check now lives in the service rather
    # than only in the route that happens to call it.
    with pytest.raises(LeaveNotVisible):
        leave_service.execute_transition(seeded, outsider, request.id, "APPROVE", None)

    seeded.refresh(request)
    assert request.current_state_id == before_state
    assert history_count(seeded, request) == before_history


def test_the_api_never_lets_a_state_be_set_directly(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """
    current_state_id and workflow_id are not editable fields.

    Sending them is not an error - they are simply not part of the update
    schema, so they are discarded. The only route to a new state is the
    transition endpoint.
    """
    user = staff(seeded, make_user, "forger", "EMPLOYEE", "DEPARTMENT_1")
    request = make_request(seeded, user)
    approved = state(seeded, "APPROVED")

    response = client.put(
        f"/api/leave/requests/{request.id}",
        headers=login_headers("forger"),
        json={"current_state_id": approved.id, "workflow_id": 1},
    )

    assert response.status_code == 200, response.text
    assert response.json()["state_code"] == "DRAFT"
    seeded.refresh(request)
    assert request.current_state_id != approved.id


# ===========================================================================
# 27-31. Business-unit scope
# ===========================================================================


def test_a_manager_sees_their_unit_and_its_descendants(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(
        seeded, make_user, "branchboss", "MANAGER", "BRANCH_1", with_employee=False
    )

    rows = visible_rows(client, login_headers("branchboss"))
    names = {r["employee"]["name"] for r in rows}
    assert seeded_names_under("BRANCH_1") <= names
    assert_scoped_to(rows, "BRANCH_1")
    # Inheritance flows down: the two departments below Branch 1 are included.
    assert _EMPLOYEE_NAME["EMP-005"] in names   # Department 1
    assert _EMPLOYEE_NAME["EMP-008"] in names   # Department 2
    assert _EMPLOYEE_NAME["EMP-004"] in names   # Branch 1 itself


def test_a_manager_cannot_see_a_sibling_branch_or_another_company(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(
        seeded, make_user, "branch1boss", "MANAGER", "BRANCH_1", with_employee=False
    )

    names = visible_names(client, login_headers("branch1boss"))
    assert _EMPLOYEE_NAME["EMP-012"] not in names   # Branch 2, same company
    assert _EMPLOYEE_NAME["EMP-019"] not in names   # Company 2
    assert _EMPLOYEE_NAME["EMP-002"] not in names   # above them, at Company 1


def test_scope_never_flows_upward(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """A department manager sees their department, never the branch above it."""
    staff(
        seeded, make_user, "deptboss", "MANAGER", "DEPARTMENT_1",
        with_employee=False,
    )

    rows = visible_rows(client, login_headers("deptboss"))
    names = {r["employee"]["name"] for r in rows}
    assert seeded_names_under("DEPARTMENT_1") <= names
    assert_scoped_to(rows, "DEPARTMENT_1")
    assert _EMPLOYEE_NAME["EMP-004"] not in names   # the branch manager above


def test_hr_at_a_company_sees_the_whole_company(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "hr", "HR", "COMPANY_1", with_employee=False)

    rows = visible_rows(client, login_headers("hr"))
    names = {r["employee"]["name"] for r in rows}
    assert seeded_names_under("COMPANY_1") <= names
    assert_scoped_to(rows, "COMPANY_1")
    assert _EMPLOYEE_NAME["EMP-019"] not in names   # still not Company 2


def test_the_scope_staircase_is_strictly_nested(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """Department ⊂ Branch ⊂ Company ⊂ Headquarters, with no leaks sideways."""
    staff(seeded, make_user, "s_hq", "SUPER_ADMIN", "HQ", with_employee=False)
    staff(seeded, make_user, "s_co", "HR", "COMPANY_1", with_employee=False)
    staff(seeded, make_user, "s_br", "MANAGER", "BRANCH_1", with_employee=False)
    staff(seeded, make_user, "s_dp", "MANAGER", "DEPARTMENT_1", with_employee=False)

    hq = visible_names(client, login_headers("s_hq"))
    co = visible_names(client, login_headers("s_co"))
    br = visible_names(client, login_headers("s_br"))
    dp = visible_names(client, login_headers("s_dp"))

    assert dp < br < co < hq
    assert seeded_names_under("HQ") <= hq


def test_a_user_with_no_business_unit_sees_only_their_own_leave(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """
    No assignment means nothing, never everything - not even for a role that
    may approve.
    """
    user = make_user("unplaced", ("MANAGER",))
    employee = Employee(
        employee_code="EMP-LVX",
        user_id=user.id,
        first_name="Unplaced",
        last_name="Manager",
        email="unplaced.manager@example.local",
        business_unit_id=unit(seeded, "DEPARTMENT_1").id,
    )
    seeded.add(employee)
    seeded.commit()
    own = make_request(seeded, user)

    body = client.get(
        "/api/leave/requests",
        headers=login_headers("unplaced"),
        params={"page_size": 100},
    ).json()

    assert body["total"] == 1
    assert body["items"][0]["id"] == own.id


def test_a_user_with_neither_scope_nor_employee_sees_nothing(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("empty", ("MANAGER",))

    body = client.get(
        "/api/leave/requests",
        headers=login_headers("empty"),
        params={"page_size": 100},
    ).json()

    assert body["total"] == 0
    assert body["items"] == []


def test_an_out_of_scope_request_cannot_be_reached_by_id(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """Guessing the id is not a way around the scope filter."""
    outsider = staff(seeded, make_user, "far", "EMPLOYEE", "DEPARTMENT_5")
    theirs = make_request(seeded, outsider)
    staff(seeded, make_user, "near", "MANAGER", "BRANCH_1", with_employee=False)

    headers = login_headers("near")
    assert client.get(
        f"/api/leave/requests/{theirs.id}", headers=headers
    ).status_code == 403
    assert client.get(
        f"/api/leave/requests/{theirs.id}/history", headers=headers
    ).status_code == 403
    assert client.post(
        f"/api/leave/requests/{theirs.id}/transition",
        headers=headers,
        json={"transition_code": "APPROVE"},
    ).status_code == 403


# ===========================================================================
# 32-34. RBAC
# ===========================================================================


def test_leave_endpoints_need_authentication(client: TestClient, seeded: Session) -> None:
    assert client.get("/api/leave/requests").status_code == 401
    assert client.get("/api/leave/types").status_code == 401
    assert client.get("/api/leave/dashboard").status_code == 401


def test_a_role_without_the_application_is_refused_everything(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """
    APPLICATION_ADMIN is seeded with no applications at all, so it is the
    clean test of "RBAC first, before any leave rule runs".
    """
    staff(seeded, make_user, "noapp", "APPLICATION_ADMIN", "COMPANY_1")
    headers = login_headers("noapp")

    assert client.get("/api/leave/requests", headers=headers).status_code == 403
    assert client.get("/api/leave/types", headers=headers).status_code == 403
    assert client.get("/api/leave/dashboard", headers=headers).status_code == 403
    assert client.post(
        "/api/leave/requests", headers=headers, json={}
    ).status_code == 403


@pytest.mark.parametrize(
    "role_code", ["SUPER_ADMIN", "HR", "MANAGER", "EMPLOYEE"]
)
def test_every_leave_carrying_role_can_open_the_application(
    client: TestClient, seeded: Session, make_user, login_headers, role_code: str
) -> None:
    """Leave is self-service: an ordinary employee must get in."""
    staff(seeded, make_user, "person", role_code, "COMPANY_1")

    assert client.get(
        "/api/leave/requests", headers=login_headers("person")
    ).status_code == 200


def test_the_approval_screen_is_not_offered_to_an_employee(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """
    Screen visibility is metadata. An employee gets the two self-service
    screens and not the approval queue or the management dashboard.
    """
    staff(seeded, make_user, "selfserve", "EMPLOYEE", "DEPARTMENT_1")

    response = client.get(
        "/api/access/applications/LEAVE_MANAGEMENT/screens",
        headers=login_headers("selfserve"),
    )
    assert response.status_code == 200
    codes = {s["code"] for s in response.json()}
    assert codes == {"MY_LEAVE", "LEAVE_REQUESTS"}


def test_the_approval_screen_is_offered_to_a_manager(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "teamlead", "MANAGER", "BRANCH_1")

    response = client.get(
        "/api/access/applications/LEAVE_MANAGEMENT/screens",
        headers=login_headers("teamlead"),
    )
    codes = {s["code"] for s in response.json()}
    assert {"LEAVE_APPROVAL", "LEAVE_DASHBOARD"} <= codes


def test_platform_admin_applications_are_unaffected_by_stage_9(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """Adding Leave must not have widened anybody's platform access."""
    staff(seeded, make_user, "worker2", "EMPLOYEE", "DEPARTMENT_1")
    staff(seeded, make_user, "lead2", "MANAGER", "BRANCH_1")

    for username in ("worker2", "lead2"):
        headers = login_headers(username)
        assert client.get("/api/users", headers=headers).status_code == 403
        assert client.get("/api/roles", headers=headers).status_code == 403


# ===========================================================================
# 35-39. The dashboard
# ===========================================================================


def test_dashboard_totals_match_the_database(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "dashadmin", "SUPER_ADMIN", "HQ", with_employee=False)
    headers = login_headers("dashadmin")

    summary = client.get("/api/leave/dashboard", headers=headers).json()
    rows = client.get(
        "/api/leave/requests", headers=headers, params={"page_size": 100}
    ).json()

    # The dashboard and the list are the same WHERE clause, so they agree
    # exactly - and both include at least every seeded request.
    assert summary["total_requests"] == rows["total"]
    assert rows["total"] >= seeded_count_under("HQ")
    assert summary["total_days_requested"] == sum(
        r["total_days"] for r in rows["items"]
    )
    # The counts add up to the whole, so nothing is double-counted or missing.
    assert sum(s["value"] for s in summary["by_status"]) == summary["total_requests"]
    assert sum(s["value"] for s in summary["by_type"]) == summary["total_requests"]
    assert sum(s["value"] for s in summary["by_month"]) == summary["total_requests"]


def test_the_dashboard_respects_business_unit_scope(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "d_hq", "SUPER_ADMIN", "HQ", with_employee=False)
    staff(seeded, make_user, "d_br", "MANAGER", "BRANCH_1", with_employee=False)

    hq = client.get("/api/leave/dashboard", headers=login_headers("d_hq")).json()
    br = client.get("/api/leave/dashboard", headers=login_headers("d_br")).json()

    assert hq["total_requests"] >= seeded_count_under("HQ")
    assert br["total_requests"] >= seeded_count_under("BRANCH_1")
    assert br["total_requests"] < hq["total_requests"]
    assert br["total_days_requested"] < hq["total_days_requested"]


def test_an_employees_dashboard_shows_only_their_own_leave(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """The same dashboard definition, narrowed to one person by the same rule."""
    user = staff(seeded, make_user, "solo", "EMPLOYEE", "DEPARTMENT_1")
    make_request(seeded, user, start="2026-12-01", end="2026-12-05")
    make_request(seeded, user, start="2027-01-04", end="2027-01-05")

    summary = client.get(
        "/api/leave/dashboard", headers=login_headers("solo")
    ).json()

    assert summary["total_requests"] == 2
    assert summary["total_days_requested"] == 7


def test_by_type_aggregation_is_correct(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "typer", "EMPLOYEE", "DEPARTMENT_1")
    make_request(seeded, user, start="2026-12-01", end="2026-12-02", type_code="ANNUAL")
    make_request(seeded, user, start="2026-12-08", end="2026-12-09", type_code="ANNUAL")
    make_request(seeded, user, start="2026-12-15", end="2026-12-15", type_code="SICK")

    summary = client.get(
        "/api/leave/dashboard", headers=login_headers("typer")
    ).json()
    by_type = {row["name"]: row["value"] for row in summary["by_type"]}

    assert by_type == {"Annual Leave": 2, "Sick Leave": 1}


def test_by_status_aggregation_uses_metadata_state_names(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    manager = staff(seeded, make_user, "statusboss", "MANAGER", "BRANCH_1")
    user = staff(seeded, make_user, "statuser", "EMPLOYEE", "DEPARTMENT_1")
    drafted = make_request(seeded, user, start="2026-12-01", end="2026-12-02")
    approved = make_request(seeded, user, start="2026-12-08", end="2026-12-09")
    leave_service.execute_transition(seeded, user, approved.id, "SUBMIT", None)
    leave_service.execute_transition(seeded, manager, approved.id, "APPROVE", None)

    summary = client.get(
        "/api/leave/dashboard", headers=login_headers("statuser")
    ).json()
    by_status = {row["name"]: row["value"] for row in summary["by_status"]}

    # Every state of the workflow appears, named as the metadata names it.
    assert by_status == {
        "Draft": 1,
        "Pending Approval": 0,
        "Approved": 1,
        "Rejected": 0,
        "Cancelled": 0,
    }
    assert summary["approved"] == 1
    assert summary["pending"] == 0
    assert drafted.current_state.code == "DRAFT"


def test_by_month_aggregation_groups_and_orders_by_start_date(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "monther", "EMPLOYEE", "DEPARTMENT_1")
    make_request(seeded, user, start="2027-03-02", end="2027-03-03")
    make_request(seeded, user, start="2027-01-11", end="2027-01-12")
    make_request(seeded, user, start="2027-01-25", end="2027-01-26")

    summary = client.get(
        "/api/leave/dashboard", headers=login_headers("monther")
    ).json()

    assert summary["by_month"] == [
        {"name": "2027-01", "value": 2},
        {"name": "2027-03", "value": 1},
    ]


def test_leave_widgets_are_served_with_live_scoped_values(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """
    The metadata chain end to end: the widget rows stay configuration, and the
    numbers in them come from PostgreSQL, narrowed per user.
    """
    staff(seeded, make_user, "w_hq", "SUPER_ADMIN", "HQ", with_employee=False)
    staff(seeded, make_user, "w_br", "MANAGER", "BRANCH_1", with_employee=False)

    hq = client.get(
        "/api/access/dashboards/LEAVE_OVERVIEW/data", headers=login_headers("w_hq")
    )
    br = client.get(
        "/api/access/dashboards/LEAVE_OVERVIEW/data", headers=login_headers("w_br")
    )
    assert hq.status_code == 200, hq.text
    assert br.status_code == 200, br.text

    hq_data, br_data = hq.json(), br.json()
    assert hq_data["TOTAL_REQUESTS"]["value"] >= seeded_count_under("HQ")
    assert br_data["TOTAL_REQUESTS"]["value"] >= seeded_count_under("BRANCH_1")
    # The widget is scoped exactly like the list it sits beside.
    assert br_data["TOTAL_REQUESTS"]["value"] < hq_data["TOTAL_REQUESTS"]["value"]

    # The chart widgets arrive in the shape the ECharts wrapper expects.
    assert set(hq_data["LEAVE_BY_TYPE"]) == {"categories", "series"}
    assert set(hq_data["LEAVE_BY_MONTH"]) == {"categories", "series"}
    assert "series" in hq_data["LEAVE_BY_STATUS"]
    # Zero-count states are dropped from the pie so labels cannot collide.
    assert all(s["value"] > 0 for s in hq_data["LEAVE_BY_STATUS"]["series"])


# ===========================================================================
# Listing, filtering and paging
# ===========================================================================


def test_mine_filter_narrows_to_the_callers_own_requests(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    manager = staff(seeded, make_user, "mineboss", "MANAGER", "BRANCH_1")
    own = make_request(seeded, manager)
    headers = login_headers("mineboss")

    everything = client.get(
        "/api/leave/requests", headers=headers, params={"page_size": 100}
    ).json()
    mine = client.get(
        "/api/leave/requests",
        headers=headers,
        params={"mine": "true", "page_size": 100},
    ).json()

    assert everything["total"] >= seeded_count_under("BRANCH_1") + 1
    assert everything["total"] > mine["total"]
    assert mine["total"] == 1
    assert mine["items"][0]["id"] == own.id


def test_pending_filter_returns_only_requests_awaiting_a_decision(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """
    "Pending" is derived from the metadata - not initial, not final - so the
    queue would keep working if a second approval step were added.
    """
    staff(seeded, make_user, "queueboss", "MANAGER", "BRANCH_1", with_employee=False)

    body = client.get(
        "/api/leave/requests",
        headers=login_headers("queueboss"),
        params={"pending": "true", "page_size": 100},
    ).json()

    assert body["total"] > 0
    assert {row["state_code"] for row in body["items"]} == {"PENDING_APPROVAL"}
    assert all(row["is_final"] is False for row in body["items"])
    assert all(row["is_editable"] is False for row in body["items"])


def test_state_filter_cannot_escape_the_scope(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "filterboss", "MANAGER", "BRANCH_1", with_employee=False)

    body = client.get(
        "/api/leave/requests",
        headers=login_headers("filterboss"),
        params={"state": "APPROVED", "page_size": 100},
    ).json()

    names = {row["employee"]["name"] for row in body["items"]}
    assert names <= seeded_names_under("BRANCH_1")
    assert {row["state_code"] for row in body["items"]} == {"APPROVED"}


def test_paging_reports_the_totals_the_ui_needs(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "pager", "SUPER_ADMIN", "HQ", with_employee=False)
    headers = login_headers("pager")

    first = client.get(
        "/api/leave/requests", headers=headers, params={"page": 1, "page_size": 10}
    ).json()
    second = client.get(
        "/api/leave/requests", headers=headers, params={"page": 2, "page_size": 10}
    ).json()

    total = first["total"]
    assert total >= seeded_count_under("HQ")
    assert second["total"] == total
    assert first["total_pages"] == -(-total // 10)
    assert len(first["items"]) == 10
    # No row appears on two pages.
    assert not {r["id"] for r in first["items"]} & {r["id"] for r in second["items"]}


def test_leave_types_endpoint_lists_only_active_types(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "typist", "EMPLOYEE", "DEPARTMENT_1")
    seeded.add(LeaveType(code="WITHDRAWN", name="Withdrawn Leave", is_active=False))
    seeded.commit()

    body = client.get("/api/leave/types", headers=login_headers("typist")).json()
    codes = {t["code"] for t in body}

    assert "ANNUAL" in codes
    assert "WITHDRAWN" not in codes


def test_seeded_requests_carry_a_complete_history(seeded: Session) -> None:
    """
    Fixture data is made consistent rather than left half-written: an approved
    seeded request can say who approved it.
    """
    approved = seeded.scalar(
        select(LeaveRequest)
        .join(WorkflowState, LeaveRequest.current_state_id == WorkflowState.id)
        .where(WorkflowState.code == "APPROVED")
        .limit(1)
    )
    assert approved is not None

    entries = engine.get_history(seeded, approved)
    assert [e.to_state.code for e in entries] == [
        "DRAFT", "PENDING_APPROVAL", "APPROVED"
    ]
    assert all(e.performed_by is not None for e in entries)


def test_the_seed_is_idempotent(seeded: Session) -> None:
    """Running it again must change nothing - including the leave fixtures."""
    from app.metadata.seed import seed_all

    changed = seed_all(seeded)

    assert changed["leave_types"] == 0
    assert changed["leave_requests"] == 0
    assert changed["leave_history"] == 0
    assert changed["workflows"] == 0
    assert changed["workflow_states"] == 0
    assert changed["workflow_transitions"] == 0
