"""Attendance model - was this person here, and for how long?"""

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.employee import Employee

# Attendance statuses.
#
# A validated string rather than a metadata table, following the same
# reasoning as EMPLOYMENT_STATUSES on the Employee model: the code has to
# branch on these anyway when deriving a day's status from its timestamps, so
# a lookup table would add a join and an admin screen without buying any real
# flexibility. Configuration that genuinely varies - roles, screens, workflows
# - is metadata; a five-value vocabulary the engine computes is not.
#
#   PRESENT     checked in and out, and worked a full day
#   HALF_DAY    checked in and out, but under the half-day threshold
#   INCOMPLETE  checked in and never checked out - the one a manager chases
#   ABSENT      no attendance, recorded by an authorised correction
#   ON_LEAVE    away on approved leave rather than absent
ATTENDANCE_STATUSES = ("PRESENT", "ABSENT", "HALF_DAY", "ON_LEAVE", "INCOMPLETE")

# Below this many worked minutes a completed day counts as a half day.
# Four hours out of a nominal eight.
HALF_DAY_THRESHOLD_MINUTES = 4 * 60


class Attendance(Base, TimestampMixin):
    """
    One row per employee per day.

    Kept deliberately separate from `timesheets`. They answer different
    questions and disagreeing with each other is *useful* information:

        attendance  was the employee present, and for how long?
        timesheet   what work did they record, and did it get approved?

    Merging them would make "present but nothing logged" impossible to
    express, which is exactly the gap a manager wants to see.

    Attendance is not workflow-driven. There is no approval process for having
    turned up, so it carries no `workflow_id` - unlike a timesheet, which does.
    Adding the workflow columns "for symmetry" would mean configuring a
    workflow that never has a second state.
    """

    __tablename__ = "attendance"
    __table_args__ = (
        # One record per employee per day, enforced by the database rather
        # than by a check in the service. Two browser tabs racing to check in
        # will produce one row and one error, not two rows.
        UniqueConstraint("employee_id", "attendance_date", name="uq_attendance_day"),
        # The query this table is always asked: "this person's attendance,
        # newest first" and "everyone's attendance on this date". The pair
        # serves both, because employee_id leads.
        Index("ix_attendance_employee_date", "employee_id", "attendance_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # RESTRICT: an employee with attendance history may not be deleted out
    # from under it. Employee Management sets people INACTIVE instead.
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # The working day this row belongs to, in the server's local timezone.
    # Stored as a plain date, separate from the timestamps below, so that
    # "did I already check in today?" is an index lookup rather than a
    # calculation over a timestamp range.
    attendance_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Both nullable, and the combination is what the status is derived from:
    #   check_in set, check_out null -> still at work (INCOMPLETE)
    #   both set                     -> PRESENT or HALF_DAY, by duration
    #   both null                    -> ABSENT or ON_LEAVE, recorded by HR
    check_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Derived from the two timestamps, but stored.
    #
    # The duplication is deliberate and worth stating. Every dashboard figure
    # here sums worked time across many rows, and recomputing a difference per
    # row in SQL for each chart is both slower and easy to get subtly
    # different between one query and the next. Persisting it means one
    # definition of "worked minutes", written once in the service, and every
    # reader agrees. The cost is that it must never be set by hand - the
    # service recalculates it whenever either timestamp changes, and a test
    # checks that the stored value matches the timestamps.
    worked_minutes: Mapped[int | None] = mapped_column(Integer)

    attendance_status: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )

    # Why a day was corrected, or anything else worth recording against it.
    remarks: Mapped[str | None] = mapped_column(Text)

    employee: Mapped["Employee"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<Attendance id={self.id} employee_id={self.employee_id} "
            f"date={self.attendance_date}>"
        )
