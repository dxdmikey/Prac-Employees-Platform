"""
Pydantic schemas for Employee Management.

Related records are returned as small readable objects - `{id, name}` - rather
than either a bare id the UI cannot display or a deep nested graph. Nothing
from the authentication side (password_hash, tokens) appears anywhere here.
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.employee import EMPLOYMENT_STATUSES


def _validate_email(value: str | None) -> str | None:
    """
    A deliberately light email check.

    Pydantic's EmailStr would need the extra `email-validator` package, and
    fully correct email validation by pattern is famously impossible anyway.
    For a local learning project a shape check is enough; the real test of an
    address is whether mail to it arrives, which is a later concern.
    """
    if value is None:
        return None
    value = value.strip()
    local, at, domain = value.partition("@")
    if not at or not local or "." not in domain or " " in value:
        raise ValueError("email must look like name@example.com.")
    return value


class RelatedRef(BaseModel):
    """A related record, reduced to what a screen needs to show."""

    id: int
    name: str


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_code: str
    first_name: str
    last_name: str
    full_name: str
    email: str
    phone: str | None = None
    date_of_joining: date | None = None
    job_title: str | None = None
    employment_status: str
    business_unit: RelatedRef
    manager: RelatedRef | None = None
    # Present only when this person also has a platform login.
    user_id: int | None = None
    created_at: datetime


class EmployeeListResponse(BaseModel):
    """
    A page of employees.

    The counts travel with the rows so the UI can render "showing 1-20 of 23"
    and disable its paging buttons without a second request.
    """

    items: list[EmployeeResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class EmployeeCreateRequest(BaseModel):
    employee_code: str = Field(min_length=1, max_length=50)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    date_of_joining: date | None = None
    job_title: str | None = Field(default=None, max_length=100)
    business_unit_id: int = Field(gt=0)
    manager_id: int | None = Field(default=None, gt=0)
    employment_status: str = "ACTIVE"

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        return _validate_email(value)

    @field_validator("employment_status")
    @classmethod
    def _known_status(cls, value: str) -> str:
        if value not in EMPLOYMENT_STATUSES:
            raise ValueError(
                f"employment_status must be one of {', '.join(EMPLOYMENT_STATUSES)}."
            )
        return value


class EmployeeUpdateRequest(BaseModel):
    """
    Every field optional - send only what changes.

    There is no delete endpoint. Someone who leaves is set to INACTIVE, so the
    record and its history survive; deleting them would break every reference
    to them, starting with the people who reported to them.
    """

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    date_of_joining: date | None = None
    job_title: str | None = Field(default=None, max_length=100)
    business_unit_id: int | None = Field(default=None, gt=0)
    manager_id: int | None = Field(default=None, gt=0)
    employment_status: str | None = None

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str | None) -> str | None:
        return _validate_email(value)

    @field_validator("employment_status")
    @classmethod
    def _known_status(cls, value: str | None) -> str | None:
        if value is not None and value not in EMPLOYMENT_STATUSES:
            raise ValueError(
                f"employment_status must be one of {', '.join(EMPLOYMENT_STATUSES)}."
            )
        return value


# --- dashboard ---------------------------------------------------------------


class NamedCount(BaseModel):
    """One bar or slice: a label and a number."""

    name: str
    value: int


class EmployeeDashboardResponse(BaseModel):
    """
    Aggregated employee figures, already narrowed to the caller's scope.

    Two people asking this question get different numbers, and that is
    correct - the totals are of what each of them may see.
    """

    total_employees: int
    active_employees: int
    inactive_employees: int
    on_leave_employees: int
    business_units_represented: int
    by_business_unit: list[NamedCount]
    by_status: list[NamedCount]
