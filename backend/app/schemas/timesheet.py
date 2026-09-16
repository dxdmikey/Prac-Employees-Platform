"""Pydantic schemas for Timesheets."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.employee import NamedCount, RelatedRef


class TimesheetResponse(BaseModel):
    """
    One entry as the screens need it, with its workflow state named so a badge
    can be drawn without a second lookup.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    employee: RelatedRef
    business_unit: RelatedRef
    work_date: date
    minutes: int
    hours: float
    work_description: str
    reference: str | None = None
    state_code: str
    state_name: str
    is_final: bool
    # Whether the workflow still permits editing - true only in the initial
    # state. Ownership is a separate question, re-checked on the server.
    is_editable: bool
    created_at: datetime


class TimesheetListResponse(BaseModel):
    items: list[TimesheetResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class TimesheetCreate(BaseModel):
    """
    Body of POST /api/timesheets.

    Deliberately absent: employee_id (taken from the signed-in user's linked
    employee) and any state field (the workflow's initial state applies).

    Hours rather than minutes, because that is what a person types. The
    service converts once, and the column stores minutes so that a quarter of
    an hour stays exact.
    """

    work_date: date
    hours: float = Field(gt=0, le=24)
    work_description: str = Field(min_length=1, max_length=2000)
    reference: str | None = Field(default=None, max_length=100)


class TimesheetUpdate(BaseModel):
    """Body of PATCH - only while the entry is still a draft."""

    work_date: date | None = None
    hours: float | None = Field(default=None, gt=0, le=24)
    work_description: str | None = Field(default=None, min_length=1, max_length=2000)
    reference: str | None = Field(default=None, max_length=100)


class TimesheetTransitionRequest(BaseModel):
    transition_code: str = Field(min_length=1, max_length=50)
    comments: str | None = Field(default=None, max_length=1000)


class TimesheetDashboardResponse(BaseModel):
    """Aggregates over the timesheets the caller may see."""

    total_entries: int
    draft: int
    submitted: int
    approved: int
    rejected: int
    total_hours: float
    approved_hours: float
    by_status: list[NamedCount]
    hours_by_employee: list[NamedCount]
    hours_by_week: list[NamedCount]
