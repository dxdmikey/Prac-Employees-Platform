"""Pydantic schemas for Attendance."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.employee import NamedCount, RelatedRef


class AttendanceResponse(BaseModel):
    """
    One day, as the screens need it.

    `worked_hours` is sent alongside `worked_minutes` so no component has to
    divide by 60 and round it its own way - the backend decides how a duration
    is presented, once.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    employee: RelatedRef
    business_unit: RelatedRef
    attendance_date: date
    check_in: datetime | None = None
    check_out: datetime | None = None
    worked_minutes: int | None = None
    worked_hours: float | None = None
    attendance_status: str
    remarks: str | None = None
    # True when the day is checked in but not out - the row a manager chases.
    is_open: bool


class AttendanceListResponse(BaseModel):
    items: list[AttendanceResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class TodayAttendanceResponse(BaseModel):
    """
    What the My Attendance screen needs to draw itself, in one call.

    The two booleans are the important part: the *backend* decides whether
    checking in or out is possible right now, so the buttons are not a guess
    the browser makes from timestamps it happens to hold.
    """

    attendance_date: date
    attendance: AttendanceResponse | None = None
    can_check_in: bool
    can_check_out: bool


class AttendanceCorrection(BaseModel):
    """
    Body of the correction endpoint, for an authorised administrator.

    Every field is optional: a correction usually touches one thing, such as
    adding the checkout somebody forgot. `worked_minutes` is deliberately
    absent - it is recalculated from the timestamps, never accepted.
    """

    check_in: datetime | None = None
    check_out: datetime | None = None
    attendance_status: str | None = Field(default=None, max_length=20)
    remarks: str | None = Field(default=None, max_length=1000)


class AttendanceDashboardResponse(BaseModel):
    """Aggregates over the attendance the caller may see."""

    total_records: int
    present_today: int
    incomplete_today: int
    on_leave_today: int
    total_worked_hours: int
    average_worked_hours: float
    by_status: list[NamedCount]
    by_day: list[NamedCount]
    hours_by_employee: list[NamedCount]
