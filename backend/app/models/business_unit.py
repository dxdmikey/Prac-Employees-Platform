"""
BusinessUnit model - one node of the organisation hierarchy.

A single table stores every level of the organisation:

    Headquarters
    |-- Company 1
    |     |-- Branch 1
    |     |     |-- Department 1
    |     |     +-- Department 2
    |     +-- Branch 2
    |           |-- Department 3
    |           +-- Department 4
    +-- Company 2
          +-- Branch 3

There is no companies table, no branches table and no departments table. What
a row *is* comes from business_unit_type_id; where it *sits* comes from
parent_id, which points back at this same table.
"""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.associations import user_business_units

if TYPE_CHECKING:
    from app.models.business_unit_type import BusinessUnitType
    from app.models.user import User


class BusinessUnit(Base, TimestampMixin):
    __tablename__ = "business_units"

    id: Mapped[int] = mapped_column(primary_key=True)

    business_unit_type_id: Mapped[int] = mapped_column(
        ForeignKey("business_unit_types.id"),
        nullable=False,
        index=True,
    )

    # The self-referencing foreign key: business_units.parent_id -> business_units.id
    #
    # Nullable on purpose - a NULL parent_id marks a root of the tree
    # (Headquarters). Every other row names its parent, and repeating that one
    # link gives a hierarchy of any depth.
    #
    # ondelete="RESTRICT" refuses to delete a unit that still has children, so
    # the tree can never be left with orphaned rows pointing at a missing parent.
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_units.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            default=True, server_default="true")

    # --- relationships -----------------------------------------------------
    business_unit_type: Mapped["BusinessUnitType"] = relationship(
        back_populates="business_units"
    )

    # The two sides of the self-reference. "children" walks down the tree and
    # "parent" walks up it; remote_side tells SQLAlchemy which end of the
    # foreign key is the "one" side, since both ends are the same table.
    children: Mapped[list["BusinessUnit"]] = relationship(
        back_populates="parent",
        cascade="save-update, merge",
    )
    parent: Mapped["BusinessUnit | None"] = relationship(
        back_populates="children",
        remote_side="BusinessUnit.id",
    )

    # A user may be attached to several business units, and a business unit
    # holds several users.
    users: Mapped[list["User"]] = relationship(
        secondary=user_business_units, back_populates="business_units"
    )

    def __repr__(self) -> str:
        return f"<BusinessUnit id={self.id} code={self.code!r} parent_id={self.parent_id}>"
