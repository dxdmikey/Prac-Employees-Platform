"""
Timesheet endpoints.

Every route needs the ATTENDANCE_TIMESHEET application (RBAC). Beyond that,
nothing here decides anything: which entries you can see comes from
`timesheet_service`, and which actions you may perform comes from the
TIMESHEET_APPROVAL workflow metadata by way of the Stage 7 engine.

There is no `/approve` or `/reject` route. Approving is one value of
`transition_code` on the single transition endpoint, exactly as it is for
leave, so adding a second approval step to the workflow needs no new endpoint.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_application
from app.api.workflows import _history_row, _http_error, _transition_row
from app.db.database import get_db
from app.models.timesheet import Timesheet
from app.models.user import User
from app.schemas.employee import RelatedRef
from app.schemas.timesheet import (
    TimesheetCreate,
    TimesheetDashboardResponse,
    TimesheetListResponse,
    TimesheetResponse,
    TimesheetTransitionRequest,
    TimesheetUpdate,
)
from app.schemas.workflow import WorkflowHistoryResponse, WorkflowTransitionResponse
from app.services import timesheet_service
from app.services.timesheet_service import (
    TimesheetError,
    TimesheetNoEmployee,
    TimesheetNotVisible,
)
from app.workflows import engine
from app.workflows.exceptions import WorkflowError

require_attendance_app = require_application("ATTENDANCE_TIMESHEET")

router = APIRouter(
    prefix="/api/timesheets",
    tags=["timesheets"],
    dependencies=[Depends(require_attendance_app)],
)


def _row(entry: Timesheet) -> TimesheetResponse:
    return TimesheetResponse(
        id=entry.id,
        employee=RelatedRef(id=entry.employee.id, name=entry.employee.full_name),
        business_unit=RelatedRef(
            id=entry.employee.business_unit.id,
            name=entry.employee.business_unit.name,
        ),
        work_date=entry.work_date,
        minutes=entry.minutes,
        hours=timesheet_service.minutes_to_hours(entry.minutes),
        work_description=entry.work_description,
        reference=entry.reference,
        state_code=entry.current_state.code,
        state_name=entry.current_state.name,
        is_final=entry.current_state.is_final,
        is_editable=entry.current_state.is_initial,
        created_at=entry.created_at,
    )


def _http(exc: TimesheetError) -> HTTPException:
    if isinstance(exc, TimesheetNotVisible):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, TimesheetNoEmployee):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


@router.get("/dashboard", response_model=TimesheetDashboardResponse)
def read_dashboard(
    current_user: User = Depends(require_attendance_app),
    db: Session = Depends(get_db),
) -> TimesheetDashboardResponse:
    return TimesheetDashboardResponse(
        **timesheet_service.get_dashboard_summary(db, current_user)
    )


@router.get("", response_model=TimesheetListResponse)
def list_timesheets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=timesheet_service.MAX_PAGE_SIZE),
    mine: bool = Query(False, description="Only my own entries"),
    pending: bool = Query(False, description="Only entries awaiting a decision"),
    employee_id: int | None = Query(None, ge=1),
    state: str | None = Query(None, max_length=50),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    current_user: User = Depends(require_attendance_app),
    db: Session = Depends(get_db),
) -> TimesheetListResponse:
    rows, total = timesheet_service.list_timesheets(
        db, current_user,
        page=page, page_size=page_size, mine_only=mine, pending_only=pending,
        employee_id=employee_id, state_code=state,
        date_from=date_from, date_to=date_to,
    )
    return TimesheetListResponse(
        items=[_row(r) for r in rows], total=total, page=page,
        page_size=page_size, total_pages=max(1, -(-total // page_size)),
    )


@router.post("", response_model=TimesheetResponse,
             status_code=status.HTTP_201_CREATED)
def create_timesheet(
    payload: TimesheetCreate,
    current_user: User = Depends(require_attendance_app),
    db: Session = Depends(get_db),
) -> TimesheetResponse:
    try:
        return _row(
            timesheet_service.create_timesheet(db, current_user, payload.model_dump())
        )
    except TimesheetError as exc:
        raise _http(exc) from exc
    except WorkflowError as exc:
        raise _http_error(exc) from exc


@router.get("/{timesheet_id}", response_model=TimesheetResponse)
def read_timesheet(
    timesheet_id: int,
    current_user: User = Depends(require_attendance_app),
    db: Session = Depends(get_db),
) -> TimesheetResponse:
    try:
        return _row(
            timesheet_service.get_visible_timesheet(db, current_user, timesheet_id)
        )
    except TimesheetError as exc:
        raise _http(exc) from exc


@router.patch("/{timesheet_id}", response_model=TimesheetResponse)
def update_timesheet(
    timesheet_id: int,
    payload: TimesheetUpdate,
    current_user: User = Depends(require_attendance_app),
    db: Session = Depends(get_db),
) -> TimesheetResponse:
    try:
        return _row(
            timesheet_service.update_timesheet(
                db, current_user, timesheet_id,
                payload.model_dump(exclude_unset=True),
            )
        )
    except TimesheetError as exc:
        raise _http(exc) from exc


@router.get(
    "/{timesheet_id}/available-transitions",
    response_model=list[WorkflowTransitionResponse],
)
def read_available_transitions(
    timesheet_id: int,
    current_user: User = Depends(require_attendance_app),
    db: Session = Depends(get_db),
) -> list[WorkflowTransitionResponse]:
    """
    What this user may do to this entry, right now.

    This is what the UI draws its buttons from, which is why no React
    component decides whether to show Approve.
    """
    try:
        transitions = timesheet_service.available_transitions(
            db, current_user, timesheet_id
        )
        return [_transition_row(t) for t in transitions]
    except TimesheetError as exc:
        raise _http(exc) from exc
    except WorkflowError as exc:
        raise _http_error(exc) from exc


@router.post("/{timesheet_id}/transition", response_model=TimesheetResponse)
def execute_transition(
    timesheet_id: int,
    payload: TimesheetTransitionRequest,
    current_user: User = Depends(require_attendance_app),
    db: Session = Depends(get_db),
) -> TimesheetResponse:
    """Submit, approve, reject or revise - whichever the metadata allows."""
    try:
        return _row(
            timesheet_service.execute_transition(
                db, current_user, timesheet_id,
                payload.transition_code, payload.comments,
            )
        )
    except TimesheetError as exc:
        raise _http(exc) from exc
    except WorkflowError as exc:
        raise _http_error(exc) from exc


@router.get("/{timesheet_id}/history", response_model=list[WorkflowHistoryResponse])
def read_history(
    timesheet_id: int,
    current_user: User = Depends(require_attendance_app),
    db: Session = Depends(get_db),
) -> list[WorkflowHistoryResponse]:
    try:
        entry = timesheet_service.get_visible_timesheet(db, current_user, timesheet_id)
    except TimesheetError as exc:
        raise _http(exc) from exc
    return [_history_row(h) for h in engine.get_history(db, entry)]
