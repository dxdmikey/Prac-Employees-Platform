"""Application model - one of the business applications on the platform."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.associations import role_applications

if TYPE_CHECKING:
    from app.models.role import Role
    from app.models.screen import Screen


class Application(Base, TimestampMixin):
    """
    The eight applications (Employee Management, Leave Management System,
    Payroll, Attendance & Timesheet, Expense Management, User Management, Role
    Management, User-Role Management) are rows in this table, loaded by
    app/metadata/seed.py.

    Storing them as data means the frontend can build its menu by reading this
    table instead of having the list hardcoded in JavaScript.
    """

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Presentation metadata read by the frontend.
    icon: Mapped[str | None] = mapped_column(String(100))
    route: Mapped[str | None] = mapped_column(String(255))

    # True for User Management, Role Management and User-Role Management, which
    # only a platform administrator may open.
    is_platform_admin_app: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            default=True, server_default="true")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False,
                                               default=0, server_default="0")

    # --- relationships -----------------------------------------------------
    # One application has many screens. cascade="all, delete-orphan" means
    # deleting an application also deletes its screens, which is what you want
    # for configuration that cannot exist on its own.
    screens: Mapped[list["Screen"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="Screen.display_order",
    )
    roles: Mapped[list["Role"]] = relationship(
        secondary=role_applications, back_populates="applications"
    )

    def __repr__(self) -> str:
        return f"<Application id={self.id} code={self.code!r}>"
