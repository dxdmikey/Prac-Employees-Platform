"""Pydantic schemas for Leave Management."""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.employee import NamedCount, RelatedRef


class LeaveTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None = None
    max_days: int | None = None
    is_active: bool


class LeaveRequestResponse(BaseModel):
    """
    A request as the screens need it: related records reduced to {id, name},
    and the workflow state named so a badge can be drawn without a lookup.
    """

    id: int
    employee: RelatedRef
    business_unit: RelatedRef
    leave_type: RelatedRef
    start_date: date
    end_date: date
    total_days: int
    reason: str | None = None
    state_code: str
    state_name: str
    is_final: bool
    # Whether the *workflow* still permits editing - true only while the
    # request sits in the initial state. Exposed so the UI never has to know
    # that the initial state happens to be called DRAFT, and never has to
    # reimplement the rule. Ownership is a separate question, re-checked on
    # the server when an edit is actually attempted.
    is_editable: bool
    created_at: datetime


class LeaveRequestListResponse(BaseModel):
    items: list[LeaveRequestResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class LeaveRequestCreate(BaseModel):
    """
    Body of POST /api/leave/requests.

    Deliberately absent: employee_id (taken from the signed-in user's linked
    employee), total_days (calculated on the server) and any state field (the
    workflow's initial state applies).
    """

    leave_type_id: int = Field(gt=0)
    start_date: date
    end_date: date
    reason: str | None = Field(default=None, max_length=1000)


class LeaveRequestUpdate(BaseModel):
    """Body of PUT - only while the request is still a DRAFT."""

    leave_type_id: int | None = Field(default=None, gt=0)
    start_date: date | None = None
    end_date: date | None = None
    reason: str | None = Field(default=None, max_length=1000)


class LeaveTransitionRequest(BaseModel):
    transition_code: str = Field(min_length=1, max_length=50)
    comments: str | None = Field(default=None, max_length=1000)


class LeaveDashboardResponse(BaseModel):
    """Aggregates over the requests the caller may see."""

    total_requests: int
    pending: int
    approved: int
    rejected: int
    total_days_requested: int
    by_type: list[NamedCount]
    by_status: list[NamedCount]
    by_month: list[NamedCount]
