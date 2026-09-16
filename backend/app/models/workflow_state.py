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

    Three flags carry the shape of the process:

      * is_initial     - where a new record starts. Exactly one per workflow.
      * is_final       - nothing leaves this state; the process is over.
      * is_owner_held  - while a record sits here it is on the desk of the
                         person who raised it, rather than an approver's.

    The engine itself never reads `is_owner_held`. It exists because the
    engine answers "which *roles* may perform this transition?" and an
    application usually also needs "and is this caller the right *person*?" -
    a manager may approve timesheets, but not their own.

    Marking the state rather than the transition is what makes it general.
    "Whose desk is this on?" is a property of where the record is:

        Leave      DRAFT is owner-held; PENDING_APPROVAL is not.
        Timesheet  DRAFT and REJECTED are owner-held - a rejected timesheet
                   comes back to its author to revise - while SUBMITTED is
                   with the approver.

    An application then derives the rule it needs: a transition *out of* an
    owner-held state belongs to the record's owner, and any other transition
    belongs to somebody else. That single line covers Submit, Cancel and
    Revise without naming any of them, and it is what forbids self-approval.

    Note this is separate from editability, which asks `is_initial`. A
    rejected timesheet is back with its author but is not editable until they
    revise it into Draft.
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
    # Defaults to false: an unmarked workflow keeps behaving exactly as before,
    # with every transition treated as somebody else's to perform.
    is_owner_held: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                                default=False,
                                                server_default="false")

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
