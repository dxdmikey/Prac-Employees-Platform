"""
Attendance business logic.

Assembled from existing platform pieces, like every business application here:

  * visibility  - employee_scope (own records, plus your team if you approve)
  * ownership   - the signed-in user's linked employee record
  * corrections - the EDIT permission, checked by the route through
                  require_permission, never by a role name here

There is no workflow. Turning up is not an approval process, so attendance
carries no workflow columns and no transitions - unlike a timesheet, which
does. Its "state machine" is three facts about two timestamps, and it lives in
`_apply_derived_fields` below.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.attendance import (
    ATTENDANCE_STATUSES,
    HALF_DAY_THRESHOLD_MINUTES,
    Attendance,
)
from app.models.employee import Employee
from app.models.user import User
from app.services import employee_scope

MAX_PAGE_SIZE = 100

# How many recent days the history screen shows by default.
DEFAULT_HISTORY_DAYS = 30


class AttendanceError(Exception):
    """A request the attendance rules refuse. The API turns it into 400/403/409."""


class AttendanceNotVisible(AttendanceError):
    """The record exists but the caller may not see it."""


class AttendanceNoEmployee(AttendanceError):
    """The signed-in user has no employee record, so cannot have attendance."""


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def now() -> datetime:
    """
    The current moment, as a timezone-aware local timestamp.

    One definition of "now" for the whole module, for two reasons. It is the
    single place to change if this platform ever needs a configured working
    timezone, and it lets a test freeze time by patching one function.

    Local rather than UTC is the right choice here and worth saying why: an
    attendance *day* is a working day as the people in the office experience
    it. Deriving the date from UTC would roll the day over in the middle of a
    shift for anyone east of Greenwich - in a +05:30 office, everyone who
    checked in before 05:30 would be filed under yesterday.
    """
    return datetime.now().astimezone()


def today() -> date:
    """The current working day, in the same local timezone as `now`."""
    return now().date()


# ---------------------------------------------------------------------------
# Derived fields - the one place a day's numbers are worked out
# ---------------------------------------------------------------------------


def calculate_worked_minutes(check_in: datetime | None,
                             check_out: datetime | None) -> int | None:
    """
    Whole minutes between check-in and check-out, or None if the day is not
    finished.

    Rejects a checkout before its check-in rather than returning a negative
    number. A negative duration is not a small error to be tolerated - it
    means the two timestamps are not what they claim to be, and silently
    storing it would poison every total that sums this column.
    """
    if check_in is None or check_out is None:
        return None
    if check_out < check_in:
        raise AttendanceError("Check-out cannot be earlier than check-in.")
    return int((check_out - check_in).total_seconds() // 60)


def derive_status(check_in: datetime | None, check_out: datetime | None,
                  worked_minutes: int | None) -> str:
    """
    A day's status, from its two timestamps.

        checked in, not out        -> INCOMPLETE  (still here, or forgot)
        both, under the threshold  -> HALF_DAY
        both, at or over it        -> PRESENT
        neither                    -> ABSENT

    ON_LEAVE is not derivable from timestamps - it is a fact about approved
    leave, not about attendance - so it is only ever set by a correction.
    """
    if check_in is None:
        return "ABSENT"
    if check_out is None:
        return "INCOMPLETE"
    if (worked_minutes or 0) < HALF_DAY_THRESHOLD_MINUTES:
        return "HALF_DAY"
    return "PRESENT"


def _apply_derived_fields(record: Attendance) -> None:
    """
    Recalculate worked_minutes and the status from the timestamps.

    Called after every write that touches either timestamp, so the stored
    duration can never drift away from the times it was derived from. Nothing
    outside this module assigns to `worked_minutes`.
    """
    record.worked_minutes = calculate_worked_minutes(record.check_in, record.check_out)
    record.attendance_status = derive_status(
        record.check_in, record.check_out, record.worked_minutes
    )


# ---------------------------------------------------------------------------
# Who is asking
# ---------------------------------------------------------------------------


def get_own_employee(db: Session, user: User) -> Employee | None:
    return employee_scope.get_own_employee(db, user)


def require_own_employee(db: Session, user: User) -> Employee:
    employee = employee_scope.get_own_employee(db, user)
    if employee is None:
        raise AttendanceNoEmployee(
            "Your account is not linked to an employee record, so attendance "
            "cannot be recorded for you. Ask an administrator to link it."
        )
    return employee


# ---------------------------------------------------------------------------
# Visibility - the one query every read starts from
# ---------------------------------------------------------------------------


def _visible_query(db: Session, user: User) -> Select:
    """
    The base query for every attendance read.

    Nothing in this module reads the table without going through here, so a
    new filter or endpoint cannot accidentally skip the scope check. The rule
    itself is not written here - it comes from `employee_scope`, shared with
    Leave and Timesheets.
    """
    return (
        select(Attendance)
        .options(
            selectinload(Attendance.employee).selectinload(Employee.business_unit),
        )
        .where(
            employee_scope.visible_employee_filter(db, user, Attendance.employee_id)
        )
    )


def get_visible_record(db: Session, user: User, record_id: int) -> Attendance:
    record = db.scalar(_visible_query(db, user).where(Attendance.id == record_id))
    if record is None:
        raise AttendanceNotVisible("No attendance record with that id is available to you.")
    return record


def list_attendance(
    db: Session,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
    mine_only: bool = False,
    employee_id: int | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    open_only: bool = False,
) -> tuple[list[Attendance], int]:
    """A page of visible attendance, most recent day first."""
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)

    query = _visible_query(db, user)

    if mine_only:
        own = get_own_employee(db, user)
        # -1 matches nothing: a caller with no employee record asking for
        # "mine" gets an empty page, not everyone's.
        query = query.where(Attendance.employee_id == (own.id if own else -1))

    if employee_id is not None:
        # Not trusted - it narrows the visible set, it cannot widen it,
        # because the scope filter is already applied above.
        query = query.where(Attendance.employee_id == employee_id)

    if status:
        if status not in ATTENDANCE_STATUSES:
            raise AttendanceError(
                f"Unknown attendance status {status}. "
                f"Expected one of: {', '.join(ATTENDANCE_STATUSES)}."
            )
        query = query.where(Attendance.attendance_status == status)

    if date_from is not None:
        query = query.where(Attendance.attendance_date >= date_from)
    if date_to is not None:
        query = query.where(Attendance.attendance_date <= date_to)

    if open_only:
        # Checked in and never checked out. Expressed as the facts rather than
        # by the INCOMPLETE label, so it stays correct even if a correction
        # has relabelled the day.
        query = query.where(
            Attendance.check_in.is_not(None), Attendance.check_out.is_(None)
        )

    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = list(
        db.scalars(
            query.order_by(
                Attendance.attendance_date.desc(), Attendance.employee_id
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return rows, int(total or 0)


def get_recent_history(
    db: Session, user: User, *, days: int = DEFAULT_HISTORY_DAYS
) -> list[Attendance]:
    """The caller's own last N days, newest first."""
    rows, _ = list_attendance(
        db,
        user,
        page=1,
        page_size=MAX_PAGE_SIZE,
        mine_only=True,
        date_from=today() - timedelta(days=days),
    )
    return rows


# ---------------------------------------------------------------------------
# Check in / check out
# ---------------------------------------------------------------------------


def get_today_record(db: Session, user: User) -> Attendance | None:
    """The caller's own attendance row for today, if they have one."""
    own = get_own_employee(db, user)
    if own is None:
        return None
    return db.scalar(
        _visible_query(db, user).where(
            Attendance.employee_id == own.id,
            Attendance.attendance_date == today(),
        )
    )


def check_in(db: Session, user: User) -> Attendance:
    """
    Record the start of today's working day.

    Refuses a second check-in. The database also refuses it, through the
    unique constraint on (employee, date) - this check produces the readable
    message, and the constraint is what makes it true even if two requests
    arrive at the same instant.
    """
    employee = require_own_employee(db, user)
    existing = get_today_record(db, user)

    if existing is not None and existing.check_in is not None:
        raise AttendanceError("You have already checked in today.")

    moment = now()

    if existing is not None:
        # A row exists without a check-in: someone was marked absent or on
        # leave and has turned up after all. Reuse the row rather than
        # creating a second one for the same day.
        existing.check_in = moment
        _apply_derived_fields(existing)
        db.commit()
        db.refresh(existing)
        return existing

    record = Attendance(
        employee_id=employee.id,
        attendance_date=today(),
        check_in=moment,
    )
    _apply_derived_fields(record)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def check_out(db: Session, user: User) -> Attendance:
    """
    Record the end of today's working day, and with it the worked duration.

    Three refusals, each with its own message, because "that didn't work" is
    useless to somebody standing at a screen: you never checked in, you have
    already checked out, or the clock disagrees with itself.
    """
    require_own_employee(db, user)
    record = get_today_record(db, user)

    if record is None or record.check_in is None:
        raise AttendanceError(
            "You have not checked in today, so there is nothing to check out of."
        )
    if record.check_out is not None:
        raise AttendanceError("You have already checked out today.")

    record.check_out = now()
    # Raises if the clock has gone backwards; the state is not saved.
    _apply_derived_fields(record)
    db.commit()
    db.refresh(record)
    return record


# ---------------------------------------------------------------------------
# Corrections
# ---------------------------------------------------------------------------


def correct_record(
    db: Session, user: User, record_id: int, changes: dict
) -> Attendance:
    """
    Amend a day, for an administrator who holds the EDIT permission.

    The permission is checked by the route, using the existing
    `require_permission("EDIT")` dependency; the scope is checked here, by
    resolving the record through the visible query. Both are needed, and
    neither mentions a role.

    `worked_minutes` and `attendance_status` are recalculated from whatever
    the timestamps end up being, so a correction cannot leave a row claiming a
    duration its own times do not support. A status may still be *overridden*
    afterwards - that is how a day becomes ON_LEAVE or ABSENT, which no
    timestamp could tell you.
    """
    record = get_visible_record(db, user, record_id)

    if "check_in" in changes:
        record.check_in = changes["check_in"]
    if "check_out" in changes:
        record.check_out = changes["check_out"]

    _apply_derived_fields(record)

    status = changes.get("attendance_status")
    if status is not None:
        if status not in ATTENDANCE_STATUSES:
            raise AttendanceError(
                f"Unknown attendance status {status}. "
                f"Expected one of: {', '.join(ATTENDANCE_STATUSES)}."
            )
        record.attendance_status = status

    if "remarks" in changes:
        record.remarks = changes["remarks"]

    db.commit()
    db.refresh(record)
    return record


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def get_dashboard_summary(db: Session, user: User) -> dict:
    """
    Aggregates over exactly the attendance the caller may see.

    The visible query is reused as a subquery, so the dashboard can never
    count a day the caller could not open. An employee's totals are their own
    attendance and a manager's are their team's - the same WHERE clause, not a
    different code path.
    """
    visible = _visible_query(db, user).order_by(None).subquery()
    current_day = today()

    by_status = {
        status: count
        for status, count in db.execute(
            select(visible.c.attendance_status, func.count(visible.c.id))
            .group_by(visible.c.attendance_status)
        )
    }

    # Today's headline numbers, counted from today's rows only.
    today_counts = {
        status: count
        for status, count in db.execute(
            select(visible.c.attendance_status, func.count(visible.c.id))
            .where(visible.c.attendance_date == current_day)
            .group_by(visible.c.attendance_status)
        )
    }

    total_minutes = int(
        db.scalar(
            select(func.coalesce(func.sum(visible.c.worked_minutes), 0)).select_from(
                visible
            )
        )
        or 0
    )
    completed_days = int(
        db.scalar(
            select(func.count())
            .select_from(visible)
            .where(visible.c.worked_minutes.is_not(None))
        )
        or 0
    )

    # The last two weeks, so the trend line has a shape without becoming
    # unreadable. Ordered by date, which for a date column sorts correctly.
    by_day = [
        {"name": day.isoformat(), "value": count}
        for day, count in db.execute(
            select(visible.c.attendance_date, func.count(visible.c.id))
            .where(visible.c.attendance_date >= current_day - timedelta(days=13))
            .group_by(visible.c.attendance_date)
            .order_by(visible.c.attendance_date)
        )
    ]

    # Worked hours per person, biggest first, capped so one chart cannot try
    # to draw several hundred bars.
    hours_by_employee = [
        {"name": name, "value": int(round((minutes or 0) / 60))}
        for name, minutes in db.execute(
            select(
                (Employee.first_name + " " + Employee.last_name).label("full_name"),
                func.sum(visible.c.worked_minutes),
            )
            .join(visible, visible.c.employee_id == Employee.id)
            .group_by("full_name")
            .order_by(func.sum(visible.c.worked_minutes).desc().nulls_last())
            .limit(10)
        )
    ]

    return {
        "total_records": sum(by_status.values()),
        "present_today": today_counts.get("PRESENT", 0),
        "incomplete_today": today_counts.get("INCOMPLETE", 0),
        "on_leave_today": today_counts.get("ON_LEAVE", 0),
        "total_worked_hours": int(round(total_minutes / 60)),
        "average_worked_hours": (
            round(total_minutes / completed_days / 60, 1) if completed_days else 0.0
        ),
        # Every status in a stable order, so the chart keeps its shape even
        # before one has been reached for the first time.
        "by_status": [
            {"name": status.replace("_", " ").title(), "value": by_status.get(status, 0)}
            for status in ATTENDANCE_STATUSES
        ],
        "by_day": by_day,
        "hours_by_employee": hours_by_employee,
    }
