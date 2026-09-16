"""Permission model - a single thing a role is allowed to do."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.associations import role_permissions

if TYPE_CHECKING:
    from app.models.role import Role


class Permission(Base):
    """
    Permission codes such as VIEW, CREATE, EDIT, DELETE, APPROVE, EXPORT and
    CONFIGURE are stored as rows, not as a Python enum. That is the whole point
    of a metadata-driven platform: adding a permission is an INSERT, not a code
    change and redeploy.

    This table has only created_at (no updated_at) because permission rows are
    reference data that is created once and rarely edited.
    """

    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    roles: Mapped[list["Role"]] = relationship(
        secondary=role_permissions, back_populates="permissions"
    )

    def __repr__(self) -> str:
        return f"<Permission id={self.id} code={self.code!r}>"
