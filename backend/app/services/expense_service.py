"""
Expense Management business logic.

The fourth application assembled from the same pieces, and the third driven by
the generic workflow engine:

  * visibility  - employee_scope, shared with Leave, Attendance and Timesheets
  * transitions - the Stage 7 engine, never a direct write to current_state_id
  * who may act - the EXPENSE_APPROVAL workflow's transition roles, narrowed
                  by app/workflows/ownership.py
  * ownership   - the signed-in user's linked employee record

No role name appears in this module. One state code does, twice, and the
comment beside it says why.

**Money.** Amounts are Decimal from the column to the JSON, never float. The
service never adds a float to a Decimal, and the dashboard never sums across
currencies - see `get_dashboard_summary`.

**Receipts.** The bytes live on disk under a directory this module owns, and
the name they are stored under is generated here. A filename that came from a
browser is never used to build a path. That is the whole of the upload
security story, and it is short on purpose.
"""

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.employee import Employee
from app.models.expense import DEFAULT_CURRENCY, SUPPORTED_CURRENCIES, Expense
from app.models.expense_attachment import ExpenseAttachment
from app.models.expense_category import ExpenseCategory
from app.models.user import User
from app.models.workflow_state import WorkflowState
from app.services import employee_scope
from app.workflows import engine, ownership
from app.workflows.exceptions import TransitionNotAuthorized

EXPENSE_WORKFLOW_CODE = "EXPENSE_APPROVAL"

# The two state codes named in this module, and the only two.
#
# The metadata marks a state initial, final or owner-held, but has no marker
# for "this outcome means the money is approved" as against refused or
# withdrawn. The dashboard needs that distinction for its Approved and
# Rejected tiles, so these are named here. Every other rule is derived.
APPROVED_STATE_CODE = "APPROVED"
REJECTED_STATE_CODE = "REJECTED"
CANCELLED_STATE_CODE = "CANCELLED"

MAX_PAGE_SIZE = 100

# --- receipt storage --------------------------------------------------------
#
# Local disk, deliberately. The brief rules out cloud storage and this is a
# platform that runs entirely on one machine, so a directory beside the
# application is the honest answer. It sits outside `app/` so it is obviously
# not code, and it is git-ignored so demo receipts never reach the repository.
RECEIPT_ROOT = Path(__file__).resolve().parents[2] / "uploads" / "receipts"

# What a receipt is allowed to be. An allow-list, not a block-list: the
# question "is this one of the three things we accept?" has a safe answer when
# something unexpected turns up, and "is this one of the bad things?" does not.
ALLOWED_RECEIPT_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/pdf": ".pdf",
}
MAX_RECEIPT_BYTES = 5 * 1024 * 1024        # 5 MB
MAX_ATTACHMENTS_PER_EXPENSE = 5


class ExpenseError(Exception):
    """A request the expense rules refuse. The API turns it into 400/403/409."""


class ExpenseNotVisible(ExpenseError):
    """The record exists but the caller may not see it."""


class ExpenseNoEmployee(ExpenseError):
    """The signed-in user has no employee record, so cannot claim expenses."""


# ---------------------------------------------------------------------------
# Who is asking
# ---------------------------------------------------------------------------


def get_own_employee(db: Session, user: User) -> Employee | None:
    return employee_scope.get_own_employee(db, user)


def require_own_employee(db: Session, user: User) -> Employee:
    employee = employee_scope.get_own_employee(db, user)
    if employee is None:
        raise ExpenseNoEmployee(
            "Your account is not linked to an employee record, so you cannot "
            "claim expenses. Ask an administrator to link it."
        )
    return employee


# ---------------------------------------------------------------------------
# Visibility - the one query every read starts from
# ---------------------------------------------------------------------------


def _visible_query(db: Session, user: User) -> Select:
    """
    The base query for every expense read. Nothing in this module bypasses it.

    The rule is not written here - it comes from `employee_scope`: your own
    claims always, plus anyone in your business-unit scope if you hold the
    APPROVE permission.
    """
    return (
        select(Expense)
        .options(
            selectinload(Expense.employee).selectinload(Employee.business_unit),
            selectinload(Expense.category),
            selectinload(Expense.current_state),
            selectinload(Expense.workflow),
            selectinload(Expense.attachments),
        )
        .where(employee_scope.visible_employee_filter(db, user, Expense.employee_id))
    )


def get_visible_expense(db: Session, user: User, expense_id: int) -> Expense:
    expense = db.scalar(_visible_query(db, user).where(Expense.id == expense_id))
    if expense is None:
        raise ExpenseNotVisible("No expense with that id is available to you.")
    return expense


def list_expenses(
    db: Session,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
    mine_only: bool = False,
    employee_id: int | None = None,
    category_id: int | None = None,
    state_code: str | None = None,
    pending_only: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[Expense], int]:
    """A page of visible claims, most recent expense date first."""
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)

    query = _visible_query(db, user)

    if mine_only:
        own = get_own_employee(db, user)
        # -1 matches nothing: a caller with no employee record asking for
        # "mine" gets an empty page, not everyone's.
        query = query.where(Expense.employee_id == (own.id if own else -1))

    if employee_id is not None:
        # Narrows what the caller may already see; it cannot widen it, because
        # the scope condition is applied above.
        query = query.where(Expense.employee_id == employee_id)

    if category_id is not None:
        query = query.where(Expense.category_id == category_id)

    if state_code:
        query = query.where(
            Expense.current_state_id.in_(
                select(WorkflowState.id).where(WorkflowState.code == state_code)
            )
        )
    elif pending_only:
        # "Waiting on an approver", without naming a state: it has left the
        # claimant's desk and has not finished. Derived from the two metadata
        # flags, so inserting a second approval step would not break this.
        query = query.where(
            Expense.current_state_id.in_(
                select(WorkflowState.id).where(
                    WorkflowState.is_owner_held.is_(False),
                    WorkflowState.is_final.is_(False),
                )
            )
        )

    if date_from is not None:
        query = query.where(Expense.expense_date >= date_from)
    if date_to is not None:
        query = query.where(Expense.expense_date <= date_to)

    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = list(
        db.scalars(
            query.order_by(Expense.expense_date.desc(), Expense.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return rows, int(total or 0)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def list_categories(db: Session, *, active_only: bool = True) -> list[ExpenseCategory]:
    query = select(ExpenseCategory)
    if active_only:
        query = query.where(ExpenseCategory.is_active.is_(True))
    return list(
        db.scalars(query.order_by(ExpenseCategory.display_order, ExpenseCategory.name))
    )


def _active_category(db: Session, category_id: int) -> ExpenseCategory:
    category = db.get(ExpenseCategory, category_id)
    if category is None or not category.is_active:
        raise ExpenseError("That expense category does not exist or is not active.")
    return category


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_amount(amount: Decimal) -> Decimal:
    """
    A claim must be for a positive amount, to the penny.

    Checked here as well as in the schema. A rule that lives only in a Pydantic
    model protects only the routes that happen to use that model - the seed and
    any future script go through the service instead.
    """
    if amount is None:
        raise ExpenseError("An expense needs an amount.")
    if amount <= 0:
        raise ExpenseError("An expense amount must be greater than zero.")
    # Two decimal places is what the column stores; quantizing here means the
    # value written and the value returned are the same number.
    #
    # ROUND_HALF_UP explicitly, because Decimal's default is ROUND_HALF_EVEN -
    # banker's rounding - which sends 10.005 down to 10.00. That is the right
    # default for statistics and the wrong one for money, where a half penny
    # is expected to go up. The API schema already refuses a third decimal
    # place, so this is the safety net for callers that bypass it.
    return Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def validate_currency(currency: str | None) -> str:
    if currency is None:
        return DEFAULT_CURRENCY
    code = currency.strip().upper()
    if code not in SUPPORTED_CURRENCIES:
        raise ExpenseError(
            f"{code} is not a supported currency. "
            f"Expected one of: {', '.join(SUPPORTED_CURRENCIES)}."
        )
    return code


def _require_editable(expense: Expense) -> None:
    """
    A claim may be edited only while it sits in its workflow's initial state.

    Asking `is_initial` rather than comparing against "DRAFT" is what keeps
    this metadata-driven. It is also why a *rejected* claim is not editable
    until its owner revises it back into draft: rejected is on their desk, but
    the workflow has not reopened it for changes yet.
    """
    if not expense.current_state.is_initial:
        raise ExpenseError(
            f"This expense is {expense.current_state.name} and can no longer "
            "be edited."
        )


def _require_owner(expense: Expense, employee: Employee | None) -> None:
    if employee is None or expense.employee_id != employee.id:
        raise ExpenseNotVisible("Only the employee who raised this claim may do that.")


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def create_expense(db: Session, user: User, data: dict) -> Expense:
    """
    Raise a claim against the signed-in user's own employee record.

    The owner is never taken from the request body, and the state is whatever
    the EXPENSE_APPROVAL workflow marks as initial.
    """
    employee = require_own_employee(db, user)
    _active_category(db, data["category_id"])
    amount = validate_amount(data["amount"])
    currency = validate_currency(data.get("currency"))

    workflow = engine.get_workflow(db, EXPENSE_WORKFLOW_CODE)
    initial_state = engine.get_initial_state(db, workflow)

    expense = Expense(
        employee_id=employee.id,
        category_id=data["category_id"],
        expense_date=data["expense_date"],
        amount=amount,
        currency=currency,
        merchant=(data.get("merchant") or None),
        description=data["description"].strip(),
        reference_number=(data.get("reference_number") or None),
        workflow_id=workflow.id,
        current_state_id=initial_state.id,
    )
    db.add(expense)
    db.flush()
    # The opening history line joins this same commit, so a claim and its
    # first history row appear together or not at all.
    engine.record_initial_state(db, expense, user, comments="Created")
    db.commit()
    return get_visible_expense(db, user, expense.id)


def update_expense(
    db: Session, user: User, expense_id: int, changes: dict
) -> Expense:
    """
    Edit a draft you own.

    Takes an id, not a record, so the visibility rule is resolved here and
    cannot be skipped by a caller that already holds an Expense object.
    """
    expense = get_visible_expense(db, user, expense_id)
    _require_owner(expense, get_own_employee(db, user))
    _require_editable(expense)

    if changes.get("category_id") is not None:
        _active_category(db, changes["category_id"])
        expense.category_id = changes["category_id"]
    if changes.get("expense_date") is not None:
        expense.expense_date = changes["expense_date"]
    if changes.get("amount") is not None:
        expense.amount = validate_amount(changes["amount"])
    if changes.get("currency") is not None:
        expense.currency = validate_currency(changes["currency"])
    if "merchant" in changes:
        expense.merchant = changes["merchant"] or None
    if changes.get("description") is not None:
        expense.description = changes["description"].strip()
    if "reference_number" in changes:
        expense.reference_number = changes["reference_number"] or None

    db.commit()
    db.refresh(expense)
    return expense


# ---------------------------------------------------------------------------
# Workflow - delegated to the engine
# ---------------------------------------------------------------------------


def available_transitions(db: Session, user: User, expense_id: int):
    """
    The engine's answer, narrowed by ownership.

    The engine knows which *roles* may perform a transition; it does not know
    the caller's relationship to the record. That is application knowledge, and
    `app/workflows/ownership.py` applies it from the actor marked on each
    transition.

    For EXPENSE_APPROVAL that resolves as intended without naming anything:
    Submit, Cancel and Revise are marked OWNER, Approve and Reject OTHER.
    Cancel is the one that needed the per-transition marker - it leaves
    SUBMITTED, a state that sits on the approver's desk, and is still the
    claimant's action.
    """
    expense = get_visible_expense(db, user, expense_id)
    own = get_own_employee(db, user)
    is_owner = own is not None and own.id == expense.employee_id

    return ownership.filter_for_caller(
        engine.get_available_transitions(db, expense, user), is_owner=is_owner
    )


def execute_transition(
    db: Session, user: User, expense_id: int, transition_code: str,
    comments: str | None,
) -> Expense:
    """
    Perform a transition through the engine - the only way a state changes.

    Three questions, all asked here rather than in the route, because a rule
    written in an endpoint protects only that endpoint:

      1. may this caller see this claim?           business-unit scope
      2. does the metadata allow this transition?  the engine
      3. is this caller the right person for it?   the transition's actor

    Note what this never does: assign to `expense.current_state_id`. The engine
    makes that write together with the history row, in one transaction, so a
    state change without an audit entry cannot happen - and a rejection reason
    is never lost from the decision it explains.
    """
    expense = get_visible_expense(db, user, expense_id)

    allowed = {t.code for t in available_transitions(db, user, expense_id)}
    if transition_code not in allowed:
        # Tell the two failures apart. The engine explains a metadata refusal
        # in its own words - unknown code, wrong state, missing role - so only
        # the ownership refusal is worded here.
        engine_allowed = {
            t.code for t in engine.get_available_transitions(db, expense, user)
        }
        if transition_code in engine_allowed:
            raise TransitionNotAuthorized(
                "That action is not available to you on this claim - expenses "
                "are submitted, cancelled and revised by the employee who "
                "raised them, and approved or rejected by someone else."
            )

    engine.execute_transition(db, expense, transition_code, user, comments)
    return get_visible_expense(db, user, expense_id)


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


def _receipt_path(stored_name: str) -> Path:
    """
    Where one receipt lives on disk.

    `stored_name` is always server-generated, so this cannot be pointed
    anywhere unexpected. The resolve-and-compare below is belt and braces: if
    a future change ever let a caller-supplied string reach here, the path
    would still have to be inside the receipt directory or this raises.
    """
    candidate = (RECEIPT_ROOT / stored_name).resolve()
    if not candidate.is_relative_to(RECEIPT_ROOT.resolve()):
        raise ExpenseError("That receipt could not be located.")
    return candidate


def add_attachment(
    db: Session, user: User, expense_id: int, *,
    file_name: str, content_type: str, payload: bytes,
) -> ExpenseAttachment:
    """
    Attach a receipt to a draft claim you own.

    Validated before a single byte is written: the type must be one of three,
    the size must be under the cap, and the claim must be yours and still
    editable. Attaching a receipt to a claim somebody is already reviewing
    would change what they are reviewing.
    """
    expense = get_visible_expense(db, user, expense_id)
    _require_owner(expense, get_own_employee(db, user))
    _require_editable(expense)

    if content_type not in ALLOWED_RECEIPT_TYPES:
        raise ExpenseError(
            f"{content_type or 'That file type'} cannot be attached. "
            "Receipts must be a JPEG, a PNG or a PDF."
        )
    if not payload:
        raise ExpenseError("That file is empty.")
    if len(payload) > MAX_RECEIPT_BYTES:
        raise ExpenseError(
            f"That file is too large. The limit is "
            f"{MAX_RECEIPT_BYTES // (1024 * 1024)} MB."
        )
    # Counted with a query rather than by reading `expense.attachments`.
    #
    # The session is created with expire_on_commit=False, so a collection
    # loaded earlier in this session is handed back as it was - a previous
    # upload in the same session would not appear, and the cap would never
    # bite. Asking the database is immune to that. This is the same trap that
    # made the Stage 7 engine return a stale workflow state.
    attachment_count = db.scalar(
        select(func.count())
        .select_from(ExpenseAttachment)
        .where(ExpenseAttachment.expense_id == expense.id)
    )
    if attachment_count >= MAX_ATTACHMENTS_PER_EXPENSE:
        raise ExpenseError(
            f"An expense can carry at most {MAX_ATTACHMENTS_PER_EXPENSE} receipts."
        )

    # The server names the file. Nothing the browser sent is used here, so a
    # filename like "../../../../etc/passwd" is stored as a display string and
    # never touches a path.
    stored_name = f"{uuid.uuid4().hex}{ALLOWED_RECEIPT_TYPES[content_type]}"

    RECEIPT_ROOT.mkdir(parents=True, exist_ok=True)
    _receipt_path(stored_name).write_bytes(payload)

    attachment = ExpenseAttachment(
        expense_id=expense.id,
        file_name=Path(file_name).name[:255] or "receipt",
        stored_name=stored_name,
        content_type=content_type,
        file_size=len(payload),
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    # Refresh the parent's collection too, for the same reason: a caller
    # holding the Expense must see the receipt it just added.
    db.refresh(expense, ["attachments"])
    return attachment


def get_attachment(db: Session, user: User, attachment_id: int) -> ExpenseAttachment:
    """
    One receipt, if the caller may see the claim it belongs to.

    Addressed by attachment id, and the scope check happens through the parent
    expense. There is no endpoint that takes a path.
    """
    attachment = db.get(ExpenseAttachment, attachment_id)
    if attachment is None:
        raise ExpenseNotVisible("No receipt with that id is available to you.")
    # Raises if the claim is outside the caller's scope, which is what makes
    # this safe: the same 403 whether the receipt exists or not.
    get_visible_expense(db, user, attachment.expense_id)
    return attachment


def read_attachment_bytes(attachment: ExpenseAttachment) -> bytes:
    path = _receipt_path(attachment.stored_name)
    if not path.is_file():
        raise ExpenseError("That receipt is no longer stored on this server.")
    return path.read_bytes()


def delete_attachment(db: Session, user: User, attachment_id: int) -> None:
    """Remove a receipt from a draft you own, and the file with it."""
    attachment = get_attachment(db, user, attachment_id)
    expense = get_visible_expense(db, user, attachment.expense_id)
    _require_owner(expense, get_own_employee(db, user))
    _require_editable(expense)

    path = _receipt_path(attachment.stored_name)
    db.delete(attachment)
    db.commit()
    db.refresh(expense, ["attachments"])
    # The file goes after the row commits. The other order would risk a row
    # pointing at bytes that are already gone.
    path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def get_dashboard_summary(db: Session, user: User) -> dict:
    """
    Aggregates over exactly the claims the caller may see.

    **How currencies are handled, and why it matters.** Adding 100 USD to 100
    EUR gives 200 of nothing. Converting between them needs rates this
    platform does not have and should not invent. So the totals here are
    computed for **one** currency - the one most of the caller's claims are in
    - and the response says which. `totals_by_currency` carries the rest, so a
    figure is never presented as a grand total when it is not one.

    In practice the seed uses a single currency throughout, which is what makes
    the demo numbers meaningful.
    """
    visible = _visible_query(db, user).order_by(None).subquery()

    # Every currency present, with its own total. This is the honest view.
    totals_by_currency = [
        {"currency": currency, "total": total or Decimal("0"), "count": count}
        for currency, total, count in db.execute(
            select(
                visible.c.currency,
                func.sum(visible.c.amount),
                func.count(visible.c.id),
            )
            .group_by(visible.c.currency)
            .order_by(func.count(visible.c.id).desc(), visible.c.currency)
        )
    ]
    # The reporting currency: whichever the caller uses most, falling back to
    # the platform default when they have no claims at all.
    reporting_currency = (
        totals_by_currency[0]["currency"] if totals_by_currency else DEFAULT_CURRENCY
    )
    in_currency = visible.c.currency == reporting_currency

    counts = {
        code: count
        for code, count in db.execute(
            select(WorkflowState.code, func.count(visible.c.id))
            .join(visible, visible.c.current_state_id == WorkflowState.id)
            .group_by(WorkflowState.code)
        )
    }
    amounts_by_state = {
        code: amount or Decimal("0")
        for code, amount in db.execute(
            select(WorkflowState.code, func.sum(visible.c.amount))
            .join(visible, visible.c.current_state_id == WorkflowState.id)
            .where(in_currency)
            .group_by(WorkflowState.code)
        )
    }

    workflow = engine.get_workflow(db, EXPENSE_WORKFLOW_CODE, require_active=False)
    states = engine.get_states(db, workflow)

    total_amount = db.scalar(
        select(func.coalesce(func.sum(visible.c.amount), 0))
        .select_from(visible)
        .where(in_currency)
    ) or Decimal("0")

    by_category = [
        {"name": name, "value": int(round(float(amount or 0)))}
        for name, amount in db.execute(
            select(ExpenseCategory.name, func.sum(visible.c.amount))
            .join(visible, visible.c.category_id == ExpenseCategory.id)
            .where(in_currency)
            .group_by(ExpenseCategory.name)
            .order_by(func.sum(visible.c.amount).desc().nulls_last())
        )
    ]

    # to_char gives "2026-09", which sorts the same lexically and
    # chronologically because the month is zero-padded.
    by_month = [
        {"name": month, "value": int(round(float(amount or 0)))}
        for month, amount in db.execute(
            select(
                func.to_char(visible.c.expense_date, "YYYY-MM").label("month"),
                func.sum(visible.c.amount),
            )
            .where(in_currency)
            .group_by("month")
            .order_by("month")
        )
    ]

    # "Submitted" is derived, not named: past the claimant, not yet finished.
    submitted = sum(
        counts.get(state.code, 0)
        for state in states
        if not state.is_owner_held and not state.is_final
    )
    submitted_amount = sum(
        (amounts_by_state.get(state.code, Decimal("0")) for state in states
         if not state.is_owner_held and not state.is_final),
        Decimal("0"),
    )
    # "Draft" is the initial state, not "owner-held and unfinished" - a
    # rejected claim is also back with its owner, and counting it as a draft
    # would hide the rejection behind a reassuring number.
    draft = sum(counts.get(state.code, 0) for state in states if state.is_initial)

    return {
        "currency": reporting_currency,
        "total_claims": sum(counts.values()),
        "draft": draft,
        "submitted": submitted,
        "approved": counts.get(APPROVED_STATE_CODE, 0),
        "rejected": counts.get(REJECTED_STATE_CODE, 0),
        "cancelled": counts.get(CANCELLED_STATE_CODE, 0),
        "total_amount": Decimal(total_amount).quantize(Decimal("0.01")),
        "submitted_amount": Decimal(submitted_amount).quantize(Decimal("0.01")),
        "approved_amount": Decimal(
            amounts_by_state.get(APPROVED_STATE_CODE, Decimal("0"))
        ).quantize(Decimal("0.01")),
        "by_status": [
            {"name": state.name, "value": counts.get(state.code, 0)}
            for state in states
        ],
        "by_category": by_category,
        "by_month": by_month,
        "totals_by_currency": totals_by_currency,
    }
