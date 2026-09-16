"""Role model - a named bundle of permissions and application access."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.associations import (
    role_applications,
    role_permissions,
    role_screens,
    user_roles,
)

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.permission import Permission
    from app.models.screen import Screen
    from app.models.user import User


class Role(Base, TimestampMixin):
    """
    Roles are data, not code. Names such as SUPER_ADMIN, APPLICATION_ADMIN, HR,
    MANAGER and EMPLOYEE will be inserted as rows in a later stage - they are
    deliberately not written into Python as an enum, so the platform stays
    metadata-driven and new roles need no code change.
    """

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)

    # name is the human label ("Super Admin"); code is the stable machine key
    # ("SUPER_ADMIN") used in configuration and permission checks.
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # System roles are created by the platform and must not be deleted by an
    # administrator through the UI.
    is_system_role: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                                 default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            default=True, server_default="true")

    # --- relationships -----------------------------------------------------
    users: Mapped[list["User"]] = relationship(
        secondary=user_roles, back_populates="roles"
    )
    permissions: Mapped[list["Permission"]] = relationship(
        secondary=role_permissions, back_populates="roles"
    )
    applications: Mapped[list["Application"]] = relationship(
        secondary=role_applications, back_populates="roles"
    )
    screens: Mapped[list["Screen"]] = relationship(
        secondary=role_screens, back_populates="roles"
    )

    def __repr__(self) -> str:
        return f"<Role id={self.id} code={self.code!r}>"
