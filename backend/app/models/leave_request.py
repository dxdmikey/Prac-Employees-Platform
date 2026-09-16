"""LeaveRequest model - one request for time off, driven by the workflow engine."""

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.leave_type import LeaveType
    from app.models.workflow import Workflow
    from app.models.workflow_state import WorkflowState


class LeaveRequest(Base, TimestampMixin):
    """
    The second workflow-driven entity, after the Stage 7 demo record.

    It satisfies the engine's contract with the same four things - `id`,
    `__tablename__`, `workflow_id`, `current_state_id` - and the engine
    needs no change to drive it. Which states exist and who may move a request
    between them is metadata (the LEAVE_APPROVAL workflow), not code here.

    Ownership is `employee_id`, not a user id: leave belongs to the HR record.
    The signed-in user reaches it through `employees.user_id`.
    """

    __tablename__ = "leave_requests"

    id: Mapped[int] = mapped_column(primary_key=True)

    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    leave_type_id: Mapped[int] = mapped_column(
        ForeignKey("leave_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Calculated on the server from the two dates; never taken from a client.
    total_days: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)

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
    leave_type: Mapped["LeaveType"] = relationship()
    workflow: Mapped["Workflow"] = relationship()
    current_state: Mapped["WorkflowState"] = relationship()

    def __repr__(self) -> str:
        return f"<LeaveRequest id={self.id} employee_id={self.employee_id}>"
