"""Expense model - a claim for money spent, driven by the workflow engine."""

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.expense_attachment import ExpenseAttachment
    from app.models.expense_category import ExpenseCategory
    from app.models.workflow import Workflow
    from app.models.workflow_state import WorkflowState

# Currencies the platform accepts.
#
# A validated tuple rather than a table, because this list does not vary by
# customer the way categories do, and because a currency is only meaningful
# alongside conversion rates - which are deliberately out of scope here. The
# seed uses one currency throughout so that totals are honest; see
# `expense_service.get_dashboard_summary` for how mixed currencies are handled.
SUPPORTED_CURRENCIES = ("USD", "EUR", "GBP", "INR")
DEFAULT_CURRENCY = "USD"


class Expense(Base, TimestampMixin):
    """
    One expense claim, and the fourth workflow-driven entity in the platform.

    Like a leave request and a timesheet, it satisfies the engine's contract
    with four things - `id`, `__tablename__`, `workflow_id`,
    `current_state_id` - and needed no change to `engine.py`. There is no
    status column: which states exist and who may move a claim between them is
    metadata, in the EXPENSE_APPROVAL workflow.

    Ownership is `employee_id`, not a user id. A claim belongs to the HR
    record; the signed-in user reaches it through `employees.user_id`.
    """

    __tablename__ = "expenses"
    __table_args__ = (
        # The two questions this table is always asked: "my claims, newest
        # first" and "everything claimed in this period". employee_id leads,
        # so the pair serves both.
        Index("ix_expenses_employee_date", "employee_id", "expense_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # RESTRICT: an employee with claims against their name may not be deleted.
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    category_id: Mapped[int] = mapped_column(
        ForeignKey("expense_categories.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    expense_date: Mapped[date] = mapped_column(nullable=False, index=True)

    # Numeric, never Float.
    #
    # This is the one column where the type choice is not a matter of taste.
    # A binary float cannot represent 0.10 exactly, so summing a few hundred
    # of them drifts away from the figure a person would get on paper - and
    # money that does not reconcile is worse than no money at all. Numeric is
    # exact decimal arithmetic, and SQLAlchemy hands it back as Decimal.
    # 12 digits with 2 after the point covers any claim this platform will see.
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # ISO 4217, validated against SUPPORTED_CURRENCIES by the service.
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default=DEFAULT_CURRENCY,
        server_default=DEFAULT_CURRENCY,
    )

    merchant: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # A receipt or invoice number as printed on the document. Free text and
    # deliberately not unique: two suppliers can easily issue the same number.
    reference_number: Mapped[str | None] = mapped_column(String(50))

    # --- the workflow contract ---------------------------------------------
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    current_state_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_states.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    employee: Mapped["Employee"] = relationship()
    category: Mapped["ExpenseCategory"] = relationship()
    workflow: Mapped["Workflow"] = relationship()
    current_state: Mapped["WorkflowState"] = relationship()

    # Deleting a claim takes its receipts with it - an attachment has no
    # meaning on its own. The files on disk are removed by the service, which
    # is the only thing that knows where they live.
    attachments: Mapped[list["ExpenseAttachment"]] = relationship(
        back_populates="expense", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Expense id={self.id} employee_id={self.employee_id} amount={self.amount}>"
