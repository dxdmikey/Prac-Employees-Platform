"""Pydantic schemas for Expense Management."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.employee import NamedCount, RelatedRef


class ExpenseCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None = None
    is_active: bool


class ExpenseAttachmentResponse(BaseModel):
    """
    A receipt as the screens need it.

    `stored_name` is deliberately absent. The client addresses a receipt by
    its id and never learns where the bytes actually live.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    file_name: str
    content_type: str
    file_size: int
    created_at: datetime


class ExpenseResponse(BaseModel):
    """One claim, with related records reduced to what a screen shows."""

    id: int
    employee: RelatedRef
    business_unit: RelatedRef
    category: RelatedRef
    expense_date: date
    # Decimal, not float, all the way to the JSON boundary - Pydantic renders
    # it as a JSON number without going through binary floating point.
    amount: Decimal
    currency: str
    merchant: str | None = None
    description: str
    reference_number: str | None = None
    state_code: str
    state_name: str
    is_final: bool
    # Whether the workflow still permits editing: true only in the initial
    # state. Ownership is a separate question, re-checked on the server.
    is_editable: bool
    attachments: list[ExpenseAttachmentResponse] = []
    created_at: datetime


class ExpenseListResponse(BaseModel):
    items: list[ExpenseResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ExpenseCreate(BaseModel):
    """
    Body of POST /api/expenses.

    Deliberately absent: employee_id (taken from the signed-in user's linked
    employee) and any state field (the workflow's initial state applies).

    `gt=0` on the amount is the first of two checks; the service repeats it,
    because a rule that lives only in a schema protects only the routes that
    happen to use that schema.
    """

    category_id: int = Field(gt=0)
    expense_date: date
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    merchant: str | None = Field(default=None, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    reference_number: str | None = Field(default=None, max_length=50)


class ExpenseUpdate(BaseModel):
    """Body of PATCH - only while the claim is still a draft."""

    category_id: int | None = Field(default=None, gt=0)
    expense_date: date | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    merchant: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    reference_number: str | None = Field(default=None, max_length=50)


class ExpenseTransitionRequest(BaseModel):
    """
    Submit, approve, reject, cancel or revise - whichever the metadata allows.

    `comments` is where a rejection reason goes. It is stored on the workflow
    history row rather than on the expense, because it explains a decision
    rather than describing the claim.
    """

    transition_code: str = Field(min_length=1, max_length=50)
    comments: str | None = Field(default=None, max_length=1000)


class CurrencyTotal(BaseModel):
    """A sum, and the currency it is a sum of. Never one without the other."""

    currency: str
    total: Decimal
    count: int


class ExpenseDashboardResponse(BaseModel):
    """
    Aggregates over the claims the caller may see.

    Every scalar total is accompanied by `currency`, so no figure is ever
    shown without its unit. See `expense_service.get_dashboard_summary` for
    how claims in more than one currency are handled.
    """

    currency: str
    total_claims: int
    draft: int
    submitted: int
    approved: int
    rejected: int
    cancelled: int
    total_amount: Decimal
    submitted_amount: Decimal
    approved_amount: Decimal
    by_status: list[NamedCount]
    by_category: list[NamedCount]
    by_month: list[NamedCount]
    totals_by_currency: list[CurrencyTotal]
