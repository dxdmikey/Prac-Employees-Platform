"""
Tests for the generic workflow engine.

The demo workflow under test:

    DRAFT --Submit(EMPLOYEE)--> PENDING_MANAGER_APPROVAL --Approve(MANAGER)--> APPROVED
                                                          --Reject(MANAGER)--> REJECTED

Note what is missing from that diagram: there is no DRAFT -> APPROVED arrow.
Several tests below exist purely to prove the engine refuses to invent one.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.metadata.seed import seed_all
from app.models.workflow import Workflow
from app.models.workflow_demo_request import WorkflowDemoRequest
from app.models.workflow_history import WorkflowHistory
from app.models.workflow_state import WorkflowState
from app.models.workflow_transition import WorkflowTransition
from app.workflows import engine
from app.workflows.exceptions import (
    TransitionNotAuthorized,
    TransitionNotAvailable,
    TransitionNotFound,
)

DEMO = "EXPENSE_APPROVAL_DEMO"


def workflow(db: Session) -> Workflow:
    return engine.get_workflow(db, DEMO)


def state(db: Session, code: str) -> WorkflowState:
    return db.scalar(
        select(WorkflowState).where(
            WorkflowState.workflow_id == workflow(db).id, WorkflowState.code == code
        )
    )


def make_request(db: Session, user, title: str = "Laptop Purchase") -> WorkflowDemoRequest:
    """A demo record sitting in the workflow's initial state."""
    wf = workflow(db)
    request = WorkflowDemoRequest(
        title=title,
        workflow_id=wf.id,
        current_state_id=engine.get_initial_state(db, wf).id,
        created_by_user_id=user.id,
    )
    db.add(request)
    db.commit()
    return request


def history_count(db: Session, request: WorkflowDemoRequest) -> int:
    return db.scalar(
        select(func.count())
        .select_from(WorkflowHistory)
        .where(
            WorkflowHistory.entity_type == "workflow_demo_requests",
            WorkflowHistory.entity_id == request.id,
        )
    )


# --- 1-5. the definition ----------------------------------------------------


def test_workflow_is_read_from_metadata(seeded: Session) -> None:
    wf = workflow(seeded)

    assert wf.name == "Expense Approval Demo"
    assert wf.is_active
    # Platform-wide: the demo belongs to no application.
    assert wf.application_id is None


def test_states_are_linked_to_the_workflow(seeded: Session) -> None:
    states = engine.get_states(seeded, workflow(seeded))

    assert [s.code for s in states] == [
        "DRAFT", "PENDING_MANAGER_APPROVAL", "APPROVED", "REJECTED"
    ]
    assert all(s.workflow_id == workflow(seeded).id for s in states)


def test_transitions_are_linked_to_the_correct_workflow_and_states(
    seeded: Session
) -> None:
    transitions = {t.code: t for t in engine.get_transitions(seeded, workflow(seeded))}

    assert set(transitions) == {"SUBMIT", "APPROVE", "REJECT"}
    assert transitions["SUBMIT"].from_state.code == "DRAFT"
    assert transitions["SUBMIT"].to_state.code == "PENDING_MANAGER_APPROVAL"
    assert transitions["APPROVE"].to_state.code == "APPROVED"
    assert transitions["REJECT"].to_state.code == "REJECTED"

    # Every transition connects states of its own workflow.
    for transition in transitions.values():
        assert transition.workflow_id == workflow(seeded).id
        assert transition.from_state.workflow_id == transition.workflow_id
        assert transition.to_state.workflow_id == transition.workflow_id


def test_initial_state_is_identified(seeded: Session) -> None:
    assert engine.get_initial_state(seeded, workflow(seeded)).code == "DRAFT"


def test_final_states_are_identified(seeded: Session) -> None:
    finals = {s.code for s in engine.get_states(seeded, workflow(seeded)) if s.is_final}

    assert finals == {"APPROVED", "REJECTED"}
    # Nothing leaves a final state.
    for code in finals:
        outgoing = [
            t for t in engine.get_transitions(seeded, workflow(seeded))
            if t.from_state.code == code
        ]
        assert outgoing == []


# --- 6-8. transition validity -----------------------------------------------


def test_a_valid_transition_succeeds(seeded: Session, make_user) -> None:
    worker = make_user("worker", ("EMPLOYEE",))
    request = make_request(seeded, worker)

    engine.execute_transition(seeded, request, "SUBMIT", worker, "Please review")

    seeded.refresh(request)
    assert request.current_state.code == "PENDING_MANAGER_APPROVAL"


def test_an_unconfigured_transition_is_rejected(seeded: Session, make_user) -> None:
    """DRAFT -> APPROVED is not in the metadata, so it cannot happen."""
    worker = make_user("worker", ("EMPLOYEE",))
    lead = make_user("lead", ("MANAGER",))
    request = make_request(seeded, worker)

    # APPROVE exists, but not from DRAFT - and the manager is authorized for it,
    # so this is refused on the state rule alone.
    with pytest.raises(TransitionNotAvailable):
        engine.execute_transition(seeded, request, "APPROVE", lead)

    seeded.refresh(request)
    assert request.current_state.code == "DRAFT"


def test_an_unknown_transition_code_is_rejected(seeded: Session, make_user) -> None:
    worker = make_user("worker", ("EMPLOYEE",))
    request = make_request(seeded, worker)

    with pytest.raises(TransitionNotFound):
        engine.execute_transition(seeded, request, "TELEPORT", worker)


def test_transition_from_the_wrong_state_is_rejected(
    seeded: Session, make_user
) -> None:
    worker = make_user("worker", ("EMPLOYEE",))
    lead = make_user("lead", ("MANAGER",))
    request = make_request(seeded, worker)
    engine.execute_transition(seeded, request, "SUBMIT", worker)
    engine.execute_transition(seeded, request, "APPROVE", lead)

    # Already APPROVED, which is final - SUBMIT no longer applies.
    with pytest.raises(TransitionNotAvailable):
        engine.execute_transition(seeded, request, "SUBMIT", worker)


# --- 9-10. authorization ----------------------------------------------------


def test_an_unauthorized_user_cannot_execute_a_transition(
    seeded: Session, make_user
) -> None:
    """An employee may submit, but approving is a manager's transition."""
    worker = make_user("worker", ("EMPLOYEE",))
    request = make_request(seeded, worker)
    engine.execute_transition(seeded, request, "SUBMIT", worker)

    with pytest.raises(TransitionNotAuthorized):
        engine.execute_transition(seeded, request, "APPROVE", worker)

    seeded.refresh(request)
    assert request.current_state.code == "PENDING_MANAGER_APPROVAL"


def test_an_authorized_user_can_execute_a_transition(
    seeded: Session, make_user
) -> None:
    worker = make_user("worker", ("EMPLOYEE",))
    lead = make_user("lead", ("MANAGER",))
    request = make_request(seeded, worker)
    engine.execute_transition(seeded, request, "SUBMIT", worker)

    engine.execute_transition(seeded, request, "APPROVE", lead, "Looks fine")

    seeded.refresh(request)
    assert request.current_state.code == "APPROVED"


def test_a_user_with_no_roles_can_do_nothing(seeded: Session, make_user) -> None:
    worker = make_user("worker", ("EMPLOYEE",))
    nobody = make_user("nobody", ())
    request = make_request(seeded, worker)

    assert engine.get_available_transitions(seeded, request, nobody) == []
    with pytest.raises(TransitionNotAuthorized):
        engine.execute_transition(seeded, request, "SUBMIT", nobody)


def test_a_transition_with_no_roles_is_performable_by_nobody(
    seeded: Session, make_user
) -> None:
    """Unfinished configuration must fail closed, not open."""
    worker = make_user("worker", ("EMPLOYEE",))
    boss = make_user("boss", ("SUPER_ADMIN",))
    request = make_request(seeded, worker)

    submit = seeded.scalar(
        select(WorkflowTransition).where(
            WorkflowTransition.workflow_id == workflow(seeded).id,
            WorkflowTransition.code == "SUBMIT",
        )
    )
    submit.allowed_roles.clear()
    seeded.commit()

    for user in (worker, boss):
        assert engine.can_execute_transition(seeded, submit, user) is False


# --- 11-14. state, history, and what happens when it fails ------------------


def test_a_successful_transition_records_history(seeded: Session, make_user) -> None:
    worker = make_user("worker", ("EMPLOYEE",))
    lead = make_user("lead", ("MANAGER",))
    request = make_request(seeded, worker)

    engine.execute_transition(seeded, request, "SUBMIT", worker, "Please review")
    engine.execute_transition(seeded, request, "APPROVE", lead, "Approved")

    entries = engine.get_history(seeded, request)
    assert len(entries) == 2

    first, second = entries
    assert first.from_state.code == "DRAFT"
    assert first.to_state.code == "PENDING_MANAGER_APPROVAL"
    assert first.transition.code == "SUBMIT"
    assert first.performed_by_user_id == worker.id
    assert first.comments == "Please review"

    assert second.to_state.code == "APPROVED"
    assert second.performed_by_user_id == lead.id

    # The trail is generic: it names the table, not a hardcoded entity type.
    assert first.entity_type == "workflow_demo_requests"
    assert first.entity_id == request.id


@pytest.mark.parametrize(
    ("transition_code", "actor_role"),
    [("APPROVE", "MANAGER"), ("TELEPORT", "EMPLOYEE"), ("APPROVE", "EMPLOYEE")],
)
def test_a_failed_transition_changes_nothing(
    seeded: Session, make_user, transition_code: str, actor_role: str
) -> None:
    """
    No state change and no history row - whichever rule refused it.

    Covers a wrong current state, an unknown code, and a missing role.
    """
    worker = make_user("worker", ("EMPLOYEE",))
    actor = make_user("actor", (actor_role,))
    request = make_request(seeded, worker)
    before = history_count(seeded, request)

    with pytest.raises(Exception):
        engine.execute_transition(seeded, request, transition_code, actor)

    seeded.refresh(request)
    assert request.current_state.code == "DRAFT"
    assert history_count(seeded, request) == before


# --- 15-16. available transitions -------------------------------------------


def test_available_transitions_are_filtered_by_current_state(
    seeded: Session, make_user
) -> None:
    worker = make_user("worker", ("EMPLOYEE",))
    lead = make_user("lead", ("MANAGER",))
    request = make_request(seeded, worker)

    # In DRAFT the manager has nothing to do - APPROVE does not start here.
    assert engine.get_available_transitions(seeded, request, lead) == []

    engine.execute_transition(seeded, request, "SUBMIT", worker)

    assert {t.code for t in engine.get_available_transitions(seeded, request, lead)} == {
        "APPROVE", "REJECT"
    }
    # And now the employee has nothing to do.
    assert engine.get_available_transitions(seeded, request, worker) == []


def test_available_transitions_are_filtered_by_authorization(
    seeded: Session, make_user
) -> None:
    """Same record, same state, different roles, different actions."""
    worker = make_user("worker", ("EMPLOYEE",))
    lead = make_user("lead", ("MANAGER",))
    request = make_request(seeded, worker)

    assert [t.code for t in engine.get_available_transitions(seeded, request, worker)] == [
        "SUBMIT"
    ]
    assert engine.get_available_transitions(seeded, request, lead) == []


def test_a_final_state_offers_nothing(seeded: Session, make_user) -> None:
    worker = make_user("worker", ("EMPLOYEE",))
    lead = make_user("lead", ("MANAGER",))
    request = make_request(seeded, worker)
    engine.execute_transition(seeded, request, "SUBMIT", worker)
    engine.execute_transition(seeded, request, "REJECT", lead, "Not this quarter")

    seeded.refresh(request)
    assert request.current_state.code == "REJECTED"
    for user in (worker, lead):
        assert engine.get_available_transitions(seeded, request, user) == []


# --- the API ----------------------------------------------------------------


def test_full_journey_through_the_api(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("worker", ("EMPLOYEE",))
    make_user("lead", ("MANAGER",))
    worker = login_headers("worker")
    lead = login_headers("lead")

    created = client.post(
        "/api/workflow-demo",
        json={"title": "Laptop Purchase", "description": "A new laptop"},
        headers=worker,
    )
    assert created.status_code == 201
    request_id = created.json()["id"]
    assert created.json()["current_state_code"] == "DRAFT"

    # The employee is offered Submit; the manager is offered nothing yet.
    def actions(headers) -> set[str]:
        response = client.get(
            f"/api/workflow-demo/{request_id}/available-transitions", headers=headers
        )
        assert response.status_code == 200
        return {t["code"] for t in response.json()}

    assert actions(worker) == {"SUBMIT"}
    assert actions(lead) == set()

    submitted = client.post(
        f"/api/workflow-demo/{request_id}/transition",
        json={"transition_code": "SUBMIT", "comments": "Please review"},
        headers=worker,
    )
    assert submitted.status_code == 200
    assert submitted.json()["current_state_code"] == "PENDING_MANAGER_APPROVAL"

    assert actions(worker) == set()
    assert actions(lead) == {"APPROVE", "REJECT"}

    approved = client.post(
        f"/api/workflow-demo/{request_id}/transition",
        json={"transition_code": "APPROVE", "comments": "Approved"},
        headers=lead,
    )
    assert approved.status_code == 200
    assert approved.json()["current_state_code"] == "APPROVED"
    assert approved.json()["is_final"] is True

    history = client.get(
        f"/api/workflow-demo/{request_id}/history", headers=worker
    ).json()
    assert [h["to_state_code"] for h in history] == [
        "DRAFT", "PENDING_MANAGER_APPROVAL", "APPROVED"
    ]
    # The opening entry has no from-state: the record began there.
    assert history[0]["from_state_code"] is None
    assert history[0]["transition_code"] is None


def test_api_rejects_an_unauthorized_transition_with_403(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("worker", ("EMPLOYEE",))
    worker = login_headers("worker")

    request_id = client.post(
        "/api/workflow-demo", json={"title": "Chair"}, headers=worker
    ).json()["id"]
    client.post(
        f"/api/workflow-demo/{request_id}/transition",
        json={"transition_code": "SUBMIT"},
        headers=worker,
    )

    response = client.post(
        f"/api/workflow-demo/{request_id}/transition",
        json={"transition_code": "APPROVE"},
        headers=worker,
    )

    assert response.status_code == 403
    assert "do not allow" in response.json()["detail"]


def test_api_rejects_a_transition_from_the_wrong_state_with_409(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("lead", ("MANAGER",))
    lead = login_headers("lead")

    request_id = client.post(
        "/api/workflow-demo", json={"title": "Desk"}, headers=lead
    ).json()["id"]

    response = client.post(
        f"/api/workflow-demo/{request_id}/transition",
        json={"transition_code": "APPROVE"},
        headers=lead,
    )

    assert response.status_code == 409
    assert "cannot be performed" in response.json()["detail"]


def test_workflow_endpoints_need_authentication(
    client: TestClient, seeded: Session
) -> None:
    assert client.get("/api/workflows").status_code == 401
    assert client.get("/api/workflow-demo").status_code == 401


def test_workflow_definition_is_platform_administration(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("worker", ("EMPLOYEE",))
    make_user("boss", ("SUPER_ADMIN",))

    assert client.get("/api/workflows", headers=login_headers("worker")).status_code == 403
    assert client.get("/api/workflows", headers=login_headers("boss")).status_code == 200

    detail = client.get(
        f"/api/workflows/{DEMO}", headers=login_headers("boss")
    ).json()
    assert len(detail["states"]) == 4
    assert len(detail["transitions"]) == 3
    submit = next(t for t in detail["transitions"] if t["code"] == "SUBMIT")
    assert submit["allowed_role_codes"] == ["EMPLOYEE"]


def test_unknown_workflow_returns_404(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("boss", ("SUPER_ADMIN",))
    assert client.get(
        "/api/workflows/NOPE", headers=login_headers("boss")
    ).status_code == 404


# --- 17. seeding ------------------------------------------------------------


def test_workflow_metadata_is_idempotently_seeded(seeded: Session) -> None:
    before = (
        seeded.scalar(select(func.count()).select_from(Workflow)),
        seeded.scalar(select(func.count()).select_from(WorkflowState)),
        seeded.scalar(select(func.count()).select_from(WorkflowTransition)),
    )

    changed = seed_all(seeded)
    assert all(count == 0 for count in changed.values()), changed

    after = (
        seeded.scalar(select(func.count()).select_from(Workflow)),
        seeded.scalar(select(func.count()).select_from(WorkflowState)),
        seeded.scalar(select(func.count()).select_from(WorkflowTransition)),
    )
    assert before == after
