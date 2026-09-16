"""Employee model - the HR record of a person."""

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.business_unit import BusinessUnit
    from app.models.user import User

# Employment statuses.
#
# A deliberate simplification: these are a validated string rather than a
# metadata table. The platform is metadata-driven where configuration genuinely
# varies - roles, screens, workflows - but a status list of three values that
# the code must branch on anyway would add a table, a join and an admin screen
# for no real flexibility. The trade-off is that adding a status is a code
# change here plus a migration-free deploy, not an INSERT.
#
# If statuses ever need their own transitions ("who may mark someone INACTIVE"),
# the right answer is not a lookup table - it is the Stage 7 workflow engine,
# which already models exactly that.
EMPLOYMENT_STATUSES = ("ACTIVE", "INACTIVE", "ON_LEAVE")
DEFAULT_EMPLOYMENT_STATUS = "ACTIVE"


class Employee(Base, TimestampMixin):
    """
    A person as the business knows them - not as the login system knows them.

    `users` answers "who may sign in". `employees` answers "who works here,
    where, and reporting to whom". They are kept apart on purpose:

      * most employees never need a login,
      * a login may exist for someone who is not an employee (a contractor
        account, an integration user),
      * HR data should not be tangled up with authentication.

    `user_id` links the two when a person has both, and is nullable because
    most seeded employees have no account.
    """

    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The HR code. Distinct from users.employee_code, which belongs to the
    # login identity; they match for a person who has both.
    employee_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)

    # Nullable: an employee does not need a platform account. Unique so one
    # login can never be claimed by two employee records.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True
    )

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))

    date_of_joining: Mapped[date | None] = mapped_column(Date)
    job_title: Mapped[str | None] = mapped_column(String(100))

    # Where this person sits in the organisation. This single column is what
    # the Stage 5 business-unit scope filters on - everything an HR user or a
    # manager may see is decided by comparing it against their visible units.
    #
    # RESTRICT: a business unit with employees may not be deleted.
    business_unit_id: Mapped[int] = mapped_column(
        ForeignKey("business_units.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Self-reference: a manager is another employee. SET NULL rather than
    # RESTRICT so removing a manager's record does not block the delete and
    # does not silently orphan their reports - it just leaves them unmanaged.
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    employment_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=DEFAULT_EMPLOYMENT_STATUS,
        server_default=DEFAULT_EMPLOYMENT_STATUS,
        index=True,
    )

    # --- relationships -----------------------------------------------------
    user: Mapped["User | None"] = relationship()
    business_unit: Mapped["BusinessUnit"] = relationship()

    # The two ends of the self-reference. remote_side tells SQLAlchemy which
    # side is the "one", exactly as on BusinessUnit.parent.
    manager: Mapped["Employee | None"] = relationship(
        back_populates="reports", remote_side="Employee.id"
    )
    reports: Mapped[list["Employee"]] = relationship(back_populates="manager")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def __repr__(self) -> str:
        return f"<Employee id={self.id} code={self.employee_code!r}>"
