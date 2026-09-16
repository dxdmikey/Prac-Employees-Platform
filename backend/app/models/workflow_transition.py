"""WorkflowTransition model - a permitted move between two states."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.associations import workflow_transition_roles

if TYPE_CHECKING:
    from app.models.role import Role
    from app.models.workflow import Workflow
    from app.models.workflow_state import WorkflowState


class WorkflowTransition(Base, TimestampMixin):
    """
    One arrow in the diagram: FROM state to TO state, with a name.

    The set of transitions is the rulebook. If DRAFT to APPROVED is not a row,
    no amount of API calling can make it happen, because the engine only ever
    offers and executes transitions it finds here.

    allowed_roles reuses the existing RBAC roles rather than inventing a second
    permission system: which role may press Approve is metadata.
    """

    __tablename__ = "workflow_transitions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "code", name="uq_workflow_transitions_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # RESTRICT, not CASCADE: deleting a state that a transition still uses
    # would silently break the process, so the database refuses.
    from_state_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_states.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    to_state_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_states.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            default=True, server_default="true")

    workflow: Mapped["Workflow"] = relationship(back_populates="transitions")

    from_state: Mapped["WorkflowState"] = relationship(
        back_populates="outgoing_transitions", foreign_keys=[from_state_id]
    )
    to_state: Mapped["WorkflowState"] = relationship(
        back_populates="incoming_transitions", foreign_keys=[to_state_id]
    )

    # Which roles may perform this transition. An empty list means nobody -
    # a transition with no roles is configuration that is not finished.
    allowed_roles: Mapped[list["Role"]] = relationship(
        secondary=workflow_transition_roles
    )

    def __repr__(self) -> str:
        return f"<WorkflowTransition id={self.id} code={self.code!r}>"
