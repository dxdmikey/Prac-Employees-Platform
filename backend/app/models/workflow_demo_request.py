"""
WorkflowDemoRequest - a throwaway entity used to demonstrate the engine.

This is NOT Expense Management. It exists only so there is something for the
workflow engine to move through its states, and it shows the contract any
workflow-enabled entity has to satisfy:

    workflow_id        which process governs this record
    current_state_id   where it is right now

Every future entity - an expense, a leave request, a timesheet - carries the
same two columns and is driven by the same engine. That is the whole point of
building the engine before the applications.
"""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.workflow import Workflow
    from app.models.workflow_state import WorkflowState


class WorkflowDemoRequest(Base, TimestampMixin):
    __tablename__ = "workflow_demo_requests"

    id: Mapped[int] = mapped_column(primary_key=True)

    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # --- the workflow contract ---------------------------------------------
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    current_state_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_states.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    workflow: Mapped["Workflow"] = relationship()
    current_state: Mapped["WorkflowState"] = relationship()
    created_by: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return f"<WorkflowDemoRequest id={self.id} title={self.title!r}>"
