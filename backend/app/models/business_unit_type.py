"""BusinessUnitType model - the *kind* of a business unit."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.business_unit import BusinessUnit


class BusinessUnitType(Base, TimestampMixin):
    """
    Types such as Headquarters, Company, Branch and Department are rows here,
    not a Python enum. An organisation that also needs "Region" or "Team" adds
    a row; no code changes, no migration.

    display_order doubles as the depth ranking of the type (Headquarters = 1,
    Company = 2, Branch = 3, Department = 4), which is useful when rendering
    the tree or validating that a Department is not placed above a Company.
    """

    __tablename__ = "business_unit_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    display_order: Mapped[int] = mapped_column(Integer, nullable=False,
                                               default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            default=True, server_default="true")

    # One type is used by many business units.
    business_units: Mapped[list["BusinessUnit"]] = relationship(
        back_populates="business_unit_type"
    )

    def __repr__(self) -> str:
        return f"<BusinessUnitType id={self.id} code={self.code!r}>"
