"""WorkflowState model - one position in a process."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.workflow import Workflow
    from app.models.workflow_transition import WorkflowTransition


class WorkflowState(Base, TimestampMixin):
    """
    A state such as DRAFT or APPROVED.

    Two flags carry the shape of the process:

      * is_initial - where a new record starts. Exactly one per workflow.
      * is_final   - nothing leaves this state; the process is over.
    """

    __tablename__ = "workflow_states"
    __table_args__ = (
        # A code only has to be unique inside its own workflow, so two
        # different workflows may both have a DRAFT.
        UniqueConstraint("workflow_id", "code", name="uq_workflow_states_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    is_initial: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                             default=False, server_default="false")
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                           default=False, server_default="false")

    display_order: Mapped[int] = mapped_column(Integer, nullable=False,
                                               default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            default=True, server_default="true")

    workflow: Mapped["Workflow"] = relationship(back_populates="states")

    # WorkflowTransition points at this table twice (from_state and to_state),
    # so foreign_keys is required - SQLAlchemy cannot guess which column feeds
    # which list.
    outgoing_transitions: Mapped[list["WorkflowTransition"]] = relationship(
        back_populates="from_state",
        foreign_keys="WorkflowTransition.from_state_id",
    )
    incoming_transitions: Mapped[list["WorkflowTransition"]] = relationship(
        back_populates="to_state",
        foreign_keys="WorkflowTransition.to_state_id",
    )

    def __repr__(self) -> str:
        return f"<WorkflowState id={self.id} code={self.code!r}>"
