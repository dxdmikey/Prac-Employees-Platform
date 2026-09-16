"""
Leave Management endpoints.

Every route needs the LEAVE_MANAGEMENT application (RBAC). What each caller
may then see or do is decided in leave_service from ownership, the APPROVE
permission, business-unit scope and the LEAVE_APPROVAL workflow metadata -
never from a role name here.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_application
from app.api.workflows import _history_row, _http_error, _transition_row
from app.db.database import get_db
from app.models.leave_request import LeaveRequest
from app.models.leave_type import LeaveType
from app.models.user import User
from app.schemas.employee import RelatedRef
from app.schemas.leave import (
    LeaveDashboardResponse,
    LeaveRequestCreate,
    LeaveRequestListResponse,
    LeaveRequestResponse,
    LeaveRequestUpdate,
    LeaveTransitionRequest,
    LeaveTypeResponse,
)
from app.schemas.workflow import WorkflowHistoryResponse, WorkflowTransitionResponse
from app.services import leave_service
from app.services.leave_service import LeaveError, LeaveNoEmployee, LeaveNotVisible
from app.workflows import engine
from app.workflows.exceptions import WorkflowError

# Built once, at import time, and reused by every route below.
#
# Why once rather than calling require_application(...) in each signature:
# FastAPI caches a dependency's result per request keyed on the *function
# object*. Each call to the factory returns a new function, so a fresh one in
# every endpoint would run the same RBAC lookup twice on every request. One
# shared object means one lookup.
require_leave_app = require_application("LEAVE_MANAGEMENT")

router = APIRouter(
    prefix="/api/leave",
    tags=["leave"],
    dependencies=[Depends(require_leave_app)],
)


def _row(request: LeaveRequest) -> LeaveRequestResponse:
    return LeaveRequestResponse(
        id=request.id,
        employee=RelatedRef(id=request.employee.id, name=request.employee.full_name),
        business_unit=RelatedRef(
            id=request.employee.business_unit.id, name=request.employee.business_unit.name
        ),
        leave_type=RelatedRef(id=request.leave_type.id, name=request.leave_type.name),
        start_date=request.start_date,
        end_date=request.end_date,
        total_days=request.total_days,
        reason=request.reason,
        state_code=request.current_state.code,
        state_name=request.current_state.name,
        is_final=request.current_state.is_final,
        is_editable=request.current_state.is_initial,
        created_at=request.created_at,
    )


def _leave_http(exc: LeaveError) -> HTTPException:
    if isinstance(exc, LeaveNotVisible):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, LeaveNoEmployee):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


@router.get("/types", response_model=list[LeaveTypeResponse])
def list_leave_types(db: Session = Depends(get_db)) -> list[LeaveTypeResponse]:
    rows = db.scalars(
        select(LeaveType).where(LeaveType.is_active.is_(True)).order_by(LeaveType.name)
    )
    return [LeaveTypeResponse.model_validate(t) for t in rows]


@router.get("/dashboard", response_model=LeaveDashboardResponse)
def read_leave_dashboard(
    current_user: User = Depends(require_leave_app),
    db: Session = Depends(get_db),
) -> LeaveDashboardResponse:
    return LeaveDashboardResponse(**leave_service.get_dashboard_summary(db, current_user))


@router.get("/requests", response_model=LeaveRequestListResponse)
def list_requests(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=leave_service.MAX_PAGE_SIZE),
    mine: bool = Query(False, description="Only my own requests"),
    pending: bool = Query(False, description="Only requests awaiting approval"),
    state: str | None = Query(None, max_length=50),
    current_user: User = Depends(require_leave_app),
    db: Session = Depends(get_db),
) -> LeaveRequestListResponse:
    rows, total = leave_service.list_requests(
        db, current_user, page=page, page_size=page_size,
        mine_only=mine, pending_only=pending, state_code=state,
    )
    return LeaveRequestListResponse(
        items=[_row(r) for r in rows], total=total, page=page,
        page_size=page_size, total_pages=max(1, -(-total // page_size)),
    )


@router.post("/requests", response_model=LeaveRequestResponse, status_code=status.HTTP_201_CREATED)
def create_request(
    payload: LeaveRequestCreate,
    current_user: User = Depends(require_leave_app),
    db: Session = Depends(get_db),
) -> LeaveRequestResponse:
    try:
        return _row(leave_service.create_request(db, current_user, payload.model_dump()))
    except LeaveError as exc:
        raise _leave_http(exc) from exc
    except WorkflowError as exc:
        raise _http_error(exc) from exc


@router.get("/requests/{request_id}", response_model=LeaveRequestResponse)
def read_request(
    request_id: int,
    current_user: User = Depends(require_leave_app),
    db: Session = Depends(get_db),
) -> LeaveRequestResponse:
    try:
        return _row(leave_service.get_visible_request(db, current_user, request_id))
    except LeaveError as exc:
        raise _leave_http(exc) from exc


@router.put("/requests/{request_id}", response_model=LeaveRequestResponse)
def update_request(
    request_id: int,
    payload: LeaveRequestUpdate,
    current_user: User = Depends(require_leave_app),
    db: Session = Depends(get_db),
) -> LeaveRequestResponse:
    try:
        updated = leave_service.update_request(
            db, current_user, request_id, payload.model_dump(exclude_unset=True)
        )
        return _row(leave_service.get_visible_request(db, current_user, updated.id))
    except LeaveError as exc:
        raise _leave_http(exc) from exc


@router.get(
    "/requests/{request_id}/available-transitions",
    response_model=list[WorkflowTransitionResponse],
)
def read_available_transitions(
    request_id: int,
    current_user: User = Depends(require_leave_app),
    db: Session = Depends(get_db),
) -> list[WorkflowTransitionResponse]:
    try:
        transitions = leave_service.available_transitions(db, current_user, request_id)
        return [_transition_row(t) for t in transitions]
    except LeaveError as exc:
        raise _leave_http(exc) from exc
    except WorkflowError as exc:
        raise _http_error(exc) from exc


@router.post("/requests/{request_id}/transition", response_model=LeaveRequestResponse)
def execute_transition(
    request_id: int,
    payload: LeaveTransitionRequest,
    current_user: User = Depends(require_leave_app),
    db: Session = Depends(get_db),
) -> LeaveRequestResponse:
    try:
        return _row(leave_service.execute_transition(
            db, current_user, request_id, payload.transition_code, payload.comments
        ))
    except LeaveError as exc:
        raise _leave_http(exc) from exc
    except WorkflowError as exc:
        raise _http_error(exc) from exc


@router.get("/requests/{request_id}/history", response_model=list[WorkflowHistoryResponse])
def read_history(
    request_id: int,
    current_user: User = Depends(require_leave_app),
    db: Session = Depends(get_db),
) -> list[WorkflowHistoryResponse]:
    try:
        request = leave_service.get_visible_request(db, current_user, request_id)
    except LeaveError as exc:
        raise _leave_http(exc) from exc
    return [_history_row(h) for h in engine.get_history(db, request)]
