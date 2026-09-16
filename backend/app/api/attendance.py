"""
Attendance endpoints.

Every route needs the ATTENDANCE_TIMESHEET application (RBAC). What each
caller may then see or do is decided in `attendance_service` from ownership,
the APPROVE permission and business-unit scope - never from a role name here.

The one exception is the correction endpoint, which additionally declares
`require_permission("EDIT")`. That is the existing platform dependency, and it
is what separates an HR administrator from a manager without either of them
being named.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_application, require_permission
from app.db.database import get_db
from app.models.attendance import Attendance
from app.models.user import User
from app.schemas.attendance import (
    AttendanceCorrection,
    AttendanceDashboardResponse,
    AttendanceListResponse,
    AttendanceResponse,
    TodayAttendanceResponse,
)
from app.schemas.employee import RelatedRef
from app.services import attendance_service
from app.services.attendance_service import (
    AttendanceError,
    AttendanceNoEmployee,
    AttendanceNotVisible,
)

# Built once and reused by every route below, so FastAPI's per-request
# dependency cache sees one function object and runs the RBAC lookup once
# rather than once per declaration.
require_attendance_app = require_application("ATTENDANCE_TIMESHEET")

router = APIRouter(
    prefix="/api/attendance",
    tags=["attendance"],
    dependencies=[Depends(require_attendance_app)],
)


def _row(record: Attendance) -> AttendanceResponse:
    return AttendanceResponse(
        id=record.id,
        employee=RelatedRef(id=record.employee.id, name=record.employee.full_name),
        business_unit=RelatedRef(
            id=record.employee.business_unit.id,
            name=record.employee.business_unit.name,
        ),
        attendance_date=record.attendance_date,
        check_in=record.check_in,
        check_out=record.check_out,
        worked_minutes=record.worked_minutes,
        worked_hours=(
            None if record.worked_minutes is None
            else round(record.worked_minutes / 60, 2)
        ),
        attendance_status=record.attendance_status,
        remarks=record.remarks,
        is_open=record.check_in is not None and record.check_out is None,
    )


def _http(exc: AttendanceError) -> HTTPException:
    """
    Map a business failure to a status code.

    403 - it exists, but not for you
    409 - your account cannot hold attendance at all
    400 - anything else the caller got wrong
    """
    if isinstance(exc, AttendanceNotVisible):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, AttendanceNoEmployee):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


@router.get("/today", response_model=TodayAttendanceResponse)
def read_today(
    current_user: User = Depends(require_attendance_app),
    db: Session = Depends(get_db),
) -> TodayAttendanceResponse:
    """
    Today's attendance for the signed-in user, plus what they may do next.

    The two booleans are computed here rather than in the browser, so the
    Check In and Check Out buttons are the backend's answer and not a guess.
    """
    record = attendance_service.get_today_record(db, current_user)
    has_employee = attendance_service.get_own_employee(db, current_user) is not None

    return TodayAttendanceResponse(
        attendance_date=attendance_service.today(),
        attendance=None if record is None else _row(record),
        can_check_in=has_employee and (record is None or record.check_in is None),
        can_check_out=(
            has_employee
            and record is not None
            and record.check_in is not None
            and record.check_out is None
        ),
    )


@router.post("/check-in", response_model=AttendanceResponse,
             status_code=status.HTTP_201_CREATED)
def check_in(
    current_user: User = Depends(require_attendance_app),
    db: Session = Depends(get_db),
) -> AttendanceResponse:
    try:
        return _row(attendance_service.check_in(db, current_user))
    except AttendanceError as exc:
        raise _http(exc) from exc


@router.post("/check-out", response_model=AttendanceResponse)
def check_out(
    current_user: User = Depends(require_attendance_app),
    db: Session = Depends(get_db),
) -> AttendanceResponse:
    try:
        return _row(attendance_service.check_out(db, current_user))
    except AttendanceError as exc:
        raise _http(exc) from exc


@router.get("/history", response_model=list[AttendanceResponse])
def read_history(
    days: int = Query(attendance_service.DEFAULT_HISTORY_DAYS, ge=1, le=366),
    current_user: User = Depends(require_attendance_app),
    db: Session = Depends(get_db),
) -> list[AttendanceResponse]:
    """The signed-in user's own recent attendance, newest first."""
    rows = attendance_service.get_recent_history(db, current_user, days=days)
    return [_row(r) for r in rows]


@router.get("/dashboard", response_model=AttendanceDashboardResponse)
def read_dashboard(
    current_user: User = Depends(require_attendance_app),
    db: Session = Depends(get_db),
) -> AttendanceDashboardResponse:
    return AttendanceDashboardResponse(
        **attendance_service.get_dashboard_summary(db, current_user)
    )


@router.get("", response_model=AttendanceListResponse)
def list_attendance(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=attendance_service.MAX_PAGE_SIZE),
    mine: bool = Query(False, description="Only my own attendance"),
    employee_id: int | None = Query(None, ge=1),
    attendance_status: str | None = Query(None, max_length=20),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    open_only: bool = Query(False, description="Checked in but never checked out"),
    current_user: User = Depends(require_attendance_app),
    db: Session = Depends(get_db),
) -> AttendanceListResponse:
    """
    Scoped attendance - the team view.

    Every filter narrows what the caller may already see; none of them can
    widen it, because the scope condition is applied before any of them.
    """
    try:
        rows, total = attendance_service.list_attendance(
            db, current_user,
            page=page, page_size=page_size, mine_only=mine,
            employee_id=employee_id, status=attendance_status,
            date_from=date_from, date_to=date_to, open_only=open_only,
        )
    except AttendanceError as exc:
        raise _http(exc) from exc

    return AttendanceListResponse(
        items=[_row(r) for r in rows], total=total, page=page,
        page_size=page_size, total_pages=max(1, -(-total // page_size)),
    )


@router.get("/{record_id}", response_model=AttendanceResponse)
def read_record(
    record_id: int,
    current_user: User = Depends(require_attendance_app),
    db: Session = Depends(get_db),
) -> AttendanceResponse:
    try:
        return _row(attendance_service.get_visible_record(db, current_user, record_id))
    except AttendanceError as exc:
        raise _http(exc) from exc


@router.patch(
    "/{record_id}",
    response_model=AttendanceResponse,
    # Two independent requirements, both from existing platform dependencies:
    # the application (declared on the router) and the EDIT permission here.
    # Business-unit scope is the service's job and is checked there.
    dependencies=[Depends(require_permission("EDIT"))],
)
def correct_record(
    record_id: int,
    payload: AttendanceCorrection,
    current_user: User = Depends(require_attendance_app),
    db: Session = Depends(get_db),
) -> AttendanceResponse:
    """Amend a day, for an administrator who holds the EDIT permission."""
    try:
        return _row(
            attendance_service.correct_record(
                db, current_user, record_id, payload.model_dump(exclude_unset=True)
            )
        )
    except AttendanceError as exc:
        raise _http(exc) from exc
