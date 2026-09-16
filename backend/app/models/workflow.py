"""Workflow model - the definition of a state-based process."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.workflow_state import WorkflowState
    from app.models.workflow_transition import WorkflowTransition


class Workflow(Base, TimestampMixin):
    """
    One process, described entirely as data.

    A workflow is a definition, not a running thing: an expense claim moves
    DRAFT to PENDING to APPROVED, and only a manager may approve. The rows in
    workflow_states and workflow_transitions spell that out, and one generic
    engine interprets them.

    Because the definition lives in the database, adding a new process - or an
    extra approval step to an existing one - is an INSERT. No new Python
    module, and no per-application branching anywhere in the engine.
    """

    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Which application owns this workflow. NULL means a platform-wide
    # workflow that belongs to no single application - the demo workflow in
    # this stage is one.
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("applications.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            default=True, server_default="true")

    application: Mapped["Application | None"] = relationship()

    # Deleting a workflow removes its states and transitions - neither can
    # exist without the definition they belong to.
    states: Mapped[list["WorkflowState"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowState.display_order",
    )
    transitions: Mapped[list["WorkflowTransition"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowTransition.code",
    )

    def __repr__(self) -> str:
        return f"<Workflow id={self.id} code={self.code!r}>"
