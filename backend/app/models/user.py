"""User model - a person who can sign in to the platform."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.associations import user_business_units, user_roles

if TYPE_CHECKING:  # imported only for type hints, avoids circular imports
    from app.models.business_unit import BusinessUnit
    from app.models.role import Role


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    # unique=True creates a UNIQUE constraint, and PostgreSQL backs every
    # UNIQUE constraint with an index automatically - so lookups by username,
    # email or employee_code are already fast. Adding index=True as well would
    # create a second, redundant index.
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    employee_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    # Only ever a hash, never a plaintext password. bcrypt hashing arrives in
    # a later stage; the column is sized for a bcrypt hash (60 chars) with room
    # to spare in case the algorithm changes.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True,
                                            server_default="true")

    # --- relationships -----------------------------------------------------
    # A user can hold several roles, and a role is held by several users.
    roles: Mapped[list["Role"]] = relationship(
        secondary=user_roles, back_populates="users"
    )
    # A user may belong to several business units (e.g. two departments).
    business_units: Mapped[list["BusinessUnit"]] = relationship(
        secondary=user_business_units, back_populates="users"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r}>"
