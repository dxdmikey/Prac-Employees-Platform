"""Screen model - a single page inside an application."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.associations import role_screens

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.dashboard import Dashboard
    from app.models.role import Role


class Screen(Base, TimestampMixin):
    """A screen belongs to exactly one application (one-to-many)."""

    __tablename__ = "screens"
    __table_args__ = (
        # A screen code only has to be unique inside its own application, so
        # two applications may both have a screen coded "LIST".
        UniqueConstraint("application_id", "code", name="uq_screens_application_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # index=True: we constantly ask "give me the screens of application X",
    # and PostgreSQL does not index foreign keys automatically.
    #
    # Note: the UNIQUE(application_id, code) constraint above already creates an
    # index that starts with application_id, and PostgreSQL can use the leading
    # column of a multi-column index on its own - so this index is technically
    # redundant today. It is kept deliberately: it is cheap on a table this
    # size, and it keeps the foreign key indexed even if that unique constraint
    # is ever changed or dropped.
    #
    # ondelete="CASCADE" enforces the cleanup in the database itself, not just
    # in Python.
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    route: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            default=True, server_default="true")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False,
                                               default=0, server_default="0")

    # --- relationships -----------------------------------------------------
    application: Mapped["Application"] = relationship(back_populates="screens")
    dashboards: Mapped[list["Dashboard"]] = relationship(
        back_populates="screen",
        cascade="all, delete-orphan",
        order_by="Dashboard.display_order",
    )
    roles: Mapped[list["Role"]] = relationship(
        secondary=role_screens, back_populates="screens"
    )

    def __repr__(self) -> str:
        return f"<Screen id={self.id} code={self.code!r}>"
