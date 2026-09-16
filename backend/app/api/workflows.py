"""
Workflow endpoints.

Two groups:

  * **Definition** (`/api/workflows/...`) is platform configuration, so it
    reuses the existing ROLE_MANAGEMENT guard - the same one protecting roles
    and permissions.

  * **Execution** (`/api/workflow-demo/...`) is open to any signed-in user.
    It has to be: an employee submits and a manager approves, and neither is a
    platform administrator. What each of them may actually *do* is decided by
    the engine from transition metadata, not by the endpoint.

Every engine error is translated to an HTTP status here, and nowhere else, so
the engine stays free of FastAPI.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_application
from app.db.database import get_db
from app.models.user import User
from app.models.workflow_demo_request import WorkflowDemoRequest
from app.models.workflow_history import WorkflowHistory
from app.models.workflow_transition import WorkflowTransition
from app.schemas.workflow import (
    DemoRequestCreate,
    DemoRequestResponse,
    TransitionRequest,
    WorkflowDetailResponse,
    WorkflowHistoryResponse,
    WorkflowResponse,
    WorkflowStateResponse,
    WorkflowTransitionResponse,
)
from app.workflows import engine
from app.workflows.exceptions import (
    StateNotFound,
    TransitionNotAuthorized,
    TransitionNotAvailable,
    TransitionNotFound,
    WorkflowError,
    WorkflowInactive,
    WorkflowNotFound,
)

router = APIRouter(tags=["workflows"])

manage_workflows = Depends(require_application("ROLE_MANAGEMENT"))

DEMO_WORKFLOW_CODE = "EXPENSE_APPROVAL_DEMO"


def _http_error(exc: WorkflowError) -> HTTPException:
    """
    Map an engine error to a status code.

    404 - it does not exist
    403 - it exists, but not for you
    409 - it exists and you may do it, but not from where this record is now
    400 - anything else the caller got wrong

    The messages come from the engine and are written to be shown to a user.
    No stack trace ever reaches the client.
    """
    if isinstance(exc, (WorkflowNotFound, StateNotFound, TransitionNotFound)):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, TransitionNotAuthorized):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, (TransitionNotAvailable, WorkflowInactive)):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


def _transition_row(transition: WorkflowTransition) -> WorkflowTransitionResponse:
    return WorkflowTransitionResponse(
        id=transition.id,
        code=transition.code,
        name=transition.name,
        description=transition.description,
        from_state_id=transition.from_state_id,
        from_state_code=transition.from_state.code,
        from_state_name=transition.from_state.name,
        to_state_id=transition.to_state_id,
        to_state_code=transition.to_state.code,
        to_state_name=transition.to_state.name,
        allowed_role_codes=sorted(role.code for role in transition.allowed_roles),
        is_active=transition.is_active,
    )


def _request_row(request: WorkflowDemoRequest) -> DemoRequestResponse:
    return DemoRequestResponse(
        id=request.id,
        title=request.title,
        description=request.description,
        workflow_id=request.workflow_id,
        workflow_code=request.workflow.code,
        current_state_id=request.current_state_id,
        current_state_code=request.current_state.code,
        current_state_name=request.current_state.name,
        is_final=request.current_state.is_final,
        created_by_user_id=request.created_by_user_id,
        created_by_username=request.created_by.username,
        created_at=request.created_at,
    )


def _history_row(entry: WorkflowHistory) -> WorkflowHistoryResponse:
    return WorkflowHistoryResponse(
        id=entry.id,
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        from_state_code=entry.from_state.code if entry.from_state else None,
        from_state_name=entry.from_state.name if entry.from_state else None,
        to_state_code=entry.to_state.code,
        to_state_name=entry.to_state.name,
        transition_code=entry.transition.code if entry.transition else None,
        transition_name=entry.transition.name if entry.transition else None,
        performed_by_user_id=entry.performed_by_user_id,
        performed_by_username=entry.performed_by.username,
        comments=entry.comments,
        created_at=entry.created_at,
    )


# ---------------------------------------------------------------------------
# Definition - reading the metadata
# ---------------------------------------------------------------------------


@router.get(
    "/api/workflows",
    response_model=list[WorkflowResponse],
    dependencies=[manage_workflows],
)
def list_workflows(db: Session = Depends(get_db)) -> list[WorkflowResponse]:
    """Every workflow defined on the platform."""
    return [WorkflowResponse.model_validate(w) for w in engine.list_workflows(db)]


@router.get(
    "/api/workflows/{workflow_code}",
    response_model=WorkflowDetailResponse,
    dependencies=[manage_workflows],
)
def read_workflow(
    workflow_code: str, db: Session = Depends(get_db)
) -> WorkflowDetailResponse:
    """One workflow with its states and transitions - enough to draw it."""
    try:
        workflow = engine.get_workflow(db, workflow_code, require_active=False)
    except WorkflowError as exc:
        raise _http_error(exc) from exc

    return WorkflowDetailResponse(
        **WorkflowResponse.model_validate(workflow).model_dump(),
        states=[
            WorkflowStateResponse.model_validate(s)
            for s in engine.get_states(db, workflow)
        ],
        transitions=[_transition_row(t) for t in engine.get_transitions(db, workflow)],
    )


@router.get(
    "/api/workflows/{workflow_code}/states",
    response_model=list[WorkflowStateResponse],
    dependencies=[manage_workflows],
)
def list_workflow_states(
    workflow_code: str, db: Session = Depends(get_db)
) -> list[WorkflowStateResponse]:
    try:
        workflow = engine.get_workflow(db, workflow_code, require_active=False)
    except WorkflowError as exc:
        raise _http_error(exc) from exc
    return [
        WorkflowStateResponse.model_validate(s) for s in engine.get_states(db, workflow)
    ]


@router.get(
    "/api/workflows/{workflow_code}/transitions",
    response_model=list[WorkflowTransitionResponse],
    dependencies=[manage_workflows],
)
def list_workflow_transitions(
    workflow_code: str, db: Session = Depends(get_db)
) -> list[WorkflowTransitionResponse]:
    try:
        workflow = engine.get_workflow(db, workflow_code, require_active=False)
    except WorkflowError as exc:
        raise _http_error(exc) from exc
    return [_transition_row(t) for t in engine.get_transitions(db, workflow)]


# ---------------------------------------------------------------------------
# Execution - the demonstration entity
# ---------------------------------------------------------------------------


def _load_request(db: Session, request_id: int) -> WorkflowDemoRequest:
    request = db.scalar(
        select(WorkflowDemoRequest)
        .options(
            selectinload(WorkflowDemoRequest.workflow),
            selectinload(WorkflowDemoRequest.current_state),
            selectinload(WorkflowDemoRequest.created_by),
        )
        .where(WorkflowDemoRequest.id == request_id)
    )
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Request not found"
        )
    return request


@router.post(
    "/api/workflow-demo",
    response_model=DemoRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_demo_request(
    payload: DemoRequestCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DemoRequestResponse:
    """
    Create a record in the workflow's initial state.

    Which state that is comes from the metadata, not from this endpoint - the
    engine looks up the state flagged is_initial.
    """
    try:
        workflow = engine.get_workflow(db, DEMO_WORKFLOW_CODE)
        initial_state = engine.get_initial_state(db, workflow)
    except WorkflowError as exc:
        raise _http_error(exc) from exc

    request = WorkflowDemoRequest(
        title=payload.title,
        description=payload.description,
        workflow_id=workflow.id,
        current_state_id=initial_state.id,
        created_by_user_id=current_user.id,
    )
    db.add(request)
    db.flush()                    # gives the record its id for the history row

    # The opening history entry joins the same transaction, so a record can
    # never exist without the first line of its story.
    engine.record_initial_state(db, request, current_user, comments="Created")
    db.commit()

    return _request_row(_load_request(db, request.id))


@router.get("/api/workflow-demo", response_model=list[DemoRequestResponse])
def list_demo_requests(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DemoRequestResponse]:
    """
    Every demo request, newest first.

    All records are visible to everyone here on purpose: a manager has to see
    an employee's request in order to approve it. Restricting *which records*
    a person sees is business-unit scope, which belongs to the applications
    built later, not to the engine.
    """
    requests = db.scalars(
        select(WorkflowDemoRequest)
        .options(
            selectinload(WorkflowDemoRequest.workflow),
            selectinload(WorkflowDemoRequest.current_state),
            selectinload(WorkflowDemoRequest.created_by),
        )
        .order_by(WorkflowDemoRequest.id.desc())
    )
    return [_request_row(r) for r in requests]


@router.get("/api/workflow-demo/{request_id}", response_model=DemoRequestResponse)
def read_demo_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DemoRequestResponse:
    return _request_row(_load_request(db, request_id))


@router.get(
    "/api/workflow-demo/{request_id}/available-transitions",
    response_model=list[WorkflowTransitionResponse],
)
def read_available_transitions(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WorkflowTransitionResponse]:
    """
    The actions this user can take on this record, right now.

    This is what the UI turns into buttons. Because the list is filtered by
    both the current state and the user's roles, no React component ever has
    to decide which actions a role sees.
    """
    request = _load_request(db, request_id)
    try:
        transitions = engine.get_available_transitions(db, request, current_user)
    except WorkflowError as exc:
        raise _http_error(exc) from exc
    return [_transition_row(t) for t in transitions]


@router.post(
    "/api/workflow-demo/{request_id}/transition",
    response_model=DemoRequestResponse,
)
def execute_demo_transition(
    request_id: int,
    payload: TransitionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DemoRequestResponse:
    """
    Perform a transition, or explain why it is not allowed.

    Hiding a button is not the control - this endpoint re-checks everything,
    so calling it directly with curl gets the same answer the UI would.
    """
    request = _load_request(db, request_id)
    try:
        engine.execute_transition(
            db, request, payload.transition_code, current_user, payload.comments
        )
    except WorkflowError as exc:
        raise _http_error(exc) from exc

    return _request_row(_load_request(db, request_id))


@router.get(
    "/api/workflow-demo/{request_id}/history",
    response_model=list[WorkflowHistoryResponse],
)
def read_demo_history(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[WorkflowHistoryResponse]:
    """
    The audit trail, oldest first.

    Read-only by design: there is no endpoint anywhere that edits or deletes a
    history row.
    """
    request = _load_request(db, request_id)
    return [_history_row(entry) for entry in engine.get_history(db, request)]
