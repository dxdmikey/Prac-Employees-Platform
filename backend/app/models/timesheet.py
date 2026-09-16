"""Timesheet model - what work did this person record, and was it approved?"""

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.workflow import Workflow
    from app.models.workflow_state import WorkflowState


class Timesheet(Base, TimestampMixin):
    """
    One entry of recorded work, driven by the generic workflow engine.

    The third workflow-driven entity, after the Stage 7 demo record and the
    Stage 8 leave request, and it needed no change to `engine.py` at all. It
    satisfies the same four-field contract: `id`, `__tablename__`,
    `workflow_id`, `current_state_id`.

    **Why there is no unique constraint on (employee, date).** Attendance has
    one, because a person is either at work on a given day or not. A timesheet
    is the opposite: a day is normally split across several pieces of work,
    each with its own description and reference, each approved or rejected on
    its own merits. One row per day would force a whole day to be rejected
    because one line of it was wrong.

    Ownership is `employee_id`, not a user id. Work belongs to the HR record,
    and the signed-in user reaches it through `employees.user_id` - the same
    way leave does.
    """

    __tablename__ = "timesheets"
    __table_args__ = (
        # "this person's timesheets, newest first" and "everyone's entries for
        # this date" - both served by the pair, employee first.
        Index("ix_timesheets_employee_date", "employee_id", "work_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Minutes rather than hours, for the same reason money is held in cents:
    # "two and a quarter hours" is exact as 135 and approximate as 2.25. The
    # API and the UI present hours; the column stores minutes.
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    work_description: Mapped[str] = mapped_column(Text, nullable=False)

    # A free-text project, ticket or task reference. Optional, and deliberately
    # not a foreign key - there is no project table in this platform, and
    # inventing one to hold a label would be building Stage 11 early.
    reference: Mapped[str | None] = mapped_column(String(100))

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
    workflow: Mapped["Workflow"] = relationship()
    current_state: Mapped["WorkflowState"] = relationship()

    def __repr__(self) -> str:
        return f"<Timesheet id={self.id} employee_id={self.employee_id}>"
