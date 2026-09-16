"""WorkflowHistory model - the audit trail of what actually happened."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.workflow import Workflow
    from app.models.workflow_state import WorkflowState
    from app.models.workflow_transition import WorkflowTransition


class WorkflowHistory(Base):
    """
    One row per successful transition: who moved what, from where to where.

    This is the difference between definition and execution. The workflow
    tables say what *may* happen; this table says what *did*.

    The record is generic. Instead of a foreign key to one business table it
    stores a pair:

        entity_type = "workflow_demo_requests"
        entity_id   = 12

    Later that becomes ("expenses", 456) or ("leave_requests", 77) with no
    schema change - which is what lets one engine serve every application.
    The trade-off is honest: a text/id pair cannot be a real foreign key, so
    the database cannot enforce that the row exists. The engine only ever
    writes it alongside a real entity it just updated.

    There is no updated_at, and no API writes to this table. History is
    append-only; correcting it would defeat the point of having it.
    """

    __tablename__ = "workflow_history"
    __table_args__ = (
        # The question this table is always asked is "what happened to this
        # record?", so the pair is indexed together.
        Index("ix_workflow_history_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # Nullable because the very first entry of a record may have no "from":
    # it was created directly into the initial state.
    from_state_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_states.id", ondelete="RESTRICT"), nullable=True
    )
    to_state_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_states.id", ondelete="RESTRICT"), nullable=False
    )
    transition_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_transitions.id", ondelete="RESTRICT"), nullable=True
    )

    # RESTRICT so an audit trail can never be orphaned by deleting a user.
    performed_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    comments: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    workflow: Mapped["Workflow"] = relationship()
    from_state: Mapped["WorkflowState | None"] = relationship(
        foreign_keys=[from_state_id]
    )
    to_state: Mapped["WorkflowState"] = relationship(foreign_keys=[to_state_id])
    transition: Mapped["WorkflowTransition | None"] = relationship()
    performed_by: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<WorkflowHistory id={self.id} {self.entity_type}#{self.entity_id} "
            f"-> state {self.to_state_id}>"
        )
