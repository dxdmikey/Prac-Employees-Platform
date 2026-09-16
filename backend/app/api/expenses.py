"""
Expense Management endpoints.

Every route needs the EXPENSE_MANAGEMENT application (RBAC). Beyond that,
nothing here decides anything: which claims you see comes from
`expense_service`, and which actions you may perform comes from the
EXPENSE_APPROVAL workflow metadata by way of the Stage 7 engine.

There is no `/approve` or `/reject` route. Approving is one value of
`transition_code` on the single transition endpoint, exactly as it is for
leave and timesheets, so adding a second approval step to the workflow would
need no new endpoint at all.
"""

from datetime import date

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_application
from app.api.workflows import _history_row, _http_error, _transition_row
from app.db.database import get_db
from app.models.expense import Expense
from app.models.user import User
from app.schemas.employee import RelatedRef
from app.schemas.expense import (
    ExpenseAttachmentResponse,
    ExpenseCategoryResponse,
    ExpenseCreate,
    ExpenseDashboardResponse,
    ExpenseListResponse,
    ExpenseResponse,
    ExpenseTransitionRequest,
    ExpenseUpdate,
)
from app.schemas.workflow import WorkflowHistoryResponse, WorkflowTransitionResponse
from app.services import expense_service
from app.services.expense_service import (
    ExpenseError,
    ExpenseNoEmployee,
    ExpenseNotVisible,
)
from app.workflows import engine
from app.workflows.exceptions import WorkflowError

# Built once and reused, so FastAPI's per-request dependency cache sees one
# function object and runs the RBAC lookup once rather than once per route.
require_expense_app = require_application("EXPENSE_MANAGEMENT")

router = APIRouter(
    prefix="/api/expenses",
    tags=["expenses"],
    dependencies=[Depends(require_expense_app)],
)


def _row(expense: Expense) -> ExpenseResponse:
    return ExpenseResponse(
        id=expense.id,
        employee=RelatedRef(id=expense.employee.id, name=expense.employee.full_name),
        business_unit=RelatedRef(
            id=expense.employee.business_unit.id,
            name=expense.employee.business_unit.name,
        ),
        category=RelatedRef(id=expense.category.id, name=expense.category.name),
        expense_date=expense.expense_date,
        amount=expense.amount,
        currency=expense.currency,
        merchant=expense.merchant,
        description=expense.description,
        reference_number=expense.reference_number,
        state_code=expense.current_state.code,
        state_name=expense.current_state.name,
        is_final=expense.current_state.is_final,
        is_editable=expense.current_state.is_initial,
        attachments=[
            ExpenseAttachmentResponse.model_validate(a)
            for a in sorted(expense.attachments, key=lambda a: a.id)
        ],
        created_at=expense.created_at,
    )


def _http(exc: ExpenseError) -> HTTPException:
    """
    403 - it exists, but not for you
    409 - your account cannot hold expenses at all
    400 - anything else the caller got wrong
    """
    if isinstance(exc, ExpenseNotVisible):
        code = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, ExpenseNoEmployee):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    return HTTPException(status_code=code, detail=str(exc))


# --- categories and aggregates ---------------------------------------------


@router.get("/categories", response_model=list[ExpenseCategoryResponse])
def list_categories(db: Session = Depends(get_db)) -> list[ExpenseCategoryResponse]:
    """The active categories, for the form's dropdown."""
    return [
        ExpenseCategoryResponse.model_validate(c)
        for c in expense_service.list_categories(db)
    ]


@router.get("/dashboard", response_model=ExpenseDashboardResponse)
def read_dashboard(
    current_user: User = Depends(require_expense_app),
    db: Session = Depends(get_db),
) -> ExpenseDashboardResponse:
    return ExpenseDashboardResponse(
        **expense_service.get_dashboard_summary(db, current_user)
    )


# --- claims ----------------------------------------------------------------


@router.get("", response_model=ExpenseListResponse)
def list_expenses(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=expense_service.MAX_PAGE_SIZE),
    mine: bool = Query(False, description="Only my own claims"),
    pending: bool = Query(False, description="Only claims awaiting a decision"),
    employee_id: int | None = Query(None, ge=1),
    category_id: int | None = Query(None, ge=1),
    state: str | None = Query(None, max_length=50),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    current_user: User = Depends(require_expense_app),
    db: Session = Depends(get_db),
) -> ExpenseListResponse:
    rows, total = expense_service.list_expenses(
        db, current_user,
        page=page, page_size=page_size, mine_only=mine, pending_only=pending,
        employee_id=employee_id, category_id=category_id, state_code=state,
        date_from=date_from, date_to=date_to,
    )
    return ExpenseListResponse(
        items=[_row(r) for r in rows], total=total, page=page,
        page_size=page_size, total_pages=max(1, -(-total // page_size)),
    )


@router.post("", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED)
def create_expense(
    payload: ExpenseCreate,
    current_user: User = Depends(require_expense_app),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    try:
        return _row(
            expense_service.create_expense(db, current_user, payload.model_dump())
        )
    except ExpenseError as exc:
        raise _http(exc) from exc
    except WorkflowError as exc:
        raise _http_error(exc) from exc


@router.get("/{expense_id}", response_model=ExpenseResponse)
def read_expense(
    expense_id: int,
    current_user: User = Depends(require_expense_app),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    try:
        return _row(expense_service.get_visible_expense(db, current_user, expense_id))
    except ExpenseError as exc:
        raise _http(exc) from exc


@router.patch("/{expense_id}", response_model=ExpenseResponse)
def update_expense(
    expense_id: int,
    payload: ExpenseUpdate,
    current_user: User = Depends(require_expense_app),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    try:
        return _row(
            expense_service.update_expense(
                db, current_user, expense_id, payload.model_dump(exclude_unset=True)
            )
        )
    except ExpenseError as exc:
        raise _http(exc) from exc


# --- workflow --------------------------------------------------------------


@router.get(
    "/{expense_id}/available-transitions",
    response_model=list[WorkflowTransitionResponse],
)
def read_available_transitions(
    expense_id: int,
    current_user: User = Depends(require_expense_app),
    db: Session = Depends(get_db),
) -> list[WorkflowTransitionResponse]:
    """
    What this user may do to this claim, right now.

    This is what the UI draws its buttons from, which is why no React
    component decides whether to show Approve.
    """
    try:
        transitions = expense_service.available_transitions(db, current_user, expense_id)
        return [_transition_row(t) for t in transitions]
    except ExpenseError as exc:
        raise _http(exc) from exc
    except WorkflowError as exc:
        raise _http_error(exc) from exc


@router.post("/{expense_id}/transition", response_model=ExpenseResponse)
def execute_transition(
    expense_id: int,
    payload: ExpenseTransitionRequest,
    current_user: User = Depends(require_expense_app),
    db: Session = Depends(get_db),
) -> ExpenseResponse:
    """Submit, approve, reject, cancel or revise - whichever the metadata allows."""
    try:
        return _row(
            expense_service.execute_transition(
                db, current_user, expense_id,
                payload.transition_code, payload.comments,
            )
        )
    except ExpenseError as exc:
        raise _http(exc) from exc
    except WorkflowError as exc:
        raise _http_error(exc) from exc


@router.get("/{expense_id}/history", response_model=list[WorkflowHistoryResponse])
def read_history(
    expense_id: int,
    current_user: User = Depends(require_expense_app),
    db: Session = Depends(get_db),
) -> list[WorkflowHistoryResponse]:
    """The trail, including the comment an approver left when rejecting."""
    try:
        expense = expense_service.get_visible_expense(db, current_user, expense_id)
    except ExpenseError as exc:
        raise _http(exc) from exc
    return [_history_row(h) for h in engine.get_history(db, expense)]


# --- receipts ---------------------------------------------------------------


@router.post(
    "/{expense_id}/attachments",
    response_model=ExpenseAttachmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_attachment(
    expense_id: int,
    upload: UploadFile = File(..., description="JPEG, PNG or PDF, up to 5 MB"),
    current_user: User = Depends(require_expense_app),
    db: Session = Depends(get_db),
) -> ExpenseAttachmentResponse:
    """
    Attach a receipt to a draft claim.

    The whole file is read into memory before anything is validated or
    written. That is fine at a 5 MB cap and on a single-machine demo, and it
    keeps the failure modes simple: an oversized or wrong-typed upload is
    rejected without ever having created a file to clean up.
    """
    payload = await upload.read()
    try:
        attachment = expense_service.add_attachment(
            db, current_user, expense_id,
            file_name=upload.filename or "receipt",
            content_type=upload.content_type or "",
            payload=payload,
        )
    except ExpenseError as exc:
        raise _http(exc) from exc
    return ExpenseAttachmentResponse.model_validate(attachment)


@router.get("/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    current_user: User = Depends(require_expense_app),
    db: Session = Depends(get_db),
) -> Response:
    """
    Stream one receipt back, if the caller may see the claim it belongs to.

    Addressed by attachment id. No endpoint in this application accepts a
    path, and `Content-Disposition` is built from the stored display name
    rather than from anything a caller can influence at download time.
    """
    try:
        attachment = expense_service.get_attachment(db, current_user, attachment_id)
        content = expense_service.read_attachment_bytes(attachment)
    except ExpenseError as exc:
        raise _http(exc) from exc

    # Quotes escaped so a filename containing one cannot break out of the
    # header value.
    safe_name = attachment.file_name.replace('"', "")
    return Response(
        content=content,
        media_type=attachment.content_type,
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@router.delete(
    "/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_attachment(
    attachment_id: int,
    current_user: User = Depends(require_expense_app),
    db: Session = Depends(get_db),
) -> None:
    """Remove a receipt from a draft you own."""
    try:
        expense_service.delete_attachment(db, current_user, attachment_id)
    except ExpenseError as exc:
        raise _http(exc) from exc
