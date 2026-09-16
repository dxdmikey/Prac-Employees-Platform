"""
Live data for dashboard widgets.

Stage 6 built dashboards whose widgets carried their own sample numbers in
`config_json`. That proved the rendering path. This module is the next step:
a widget may instead declare where its data comes from -

    {"data_source": "employees.by_business_unit", "caption": "..."}

- and the backend fills in the values from PostgreSQL at request time.

What stays metadata-driven: which widgets exist, their titles, their chart
types, their widths, their order. What becomes live: only the numbers.

A widget with no `data_source` keeps its configured sample values, so the
dashboards from Stage 6 that have no real data behind them yet still render.
Adding a real one later is a config change plus a resolver here - never a new
dashboard page.

Every resolver receives the current user and must respect their scope. They do
that by calling `employee_service`, which cannot read employees without
narrowing to the caller's visible business units.
"""

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.models.dashboard import Dashboard
from app.models.user import User
from app.services import (
    attendance_service,
    employee_service,
    expense_service,
    leave_service,
    metadata_service,
    timesheet_service,
)

# Summaries are cached for the life of one request. A dashboard has several
# employee widgets and they would otherwise each re-run the same aggregation.
_SummaryCache = dict[str, dict]


def _employee_summary(db: Session, user: User, cache: _SummaryCache) -> dict:
    if "employees" not in cache:
        cache["employees"] = employee_service.get_dashboard_summary(db, user)
    return cache["employees"]


def _stat(value: int, caption: str) -> dict:
    return {"value": value, "caption": caption}


def _employees_total(db: Session, user: User, cache: _SummaryCache) -> dict:
    summary = _employee_summary(db, user, cache)
    return _stat(summary["total_employees"], "In your organisational scope")


def _employees_active(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(_employee_summary(db, user, cache)["active_employees"], "Currently active")


def _employees_inactive(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(_employee_summary(db, user, cache)["inactive_employees"], "No longer active")


def _employees_business_units(db: Session, user: User, cache: _SummaryCache) -> dict:
    summary = _employee_summary(db, user, cache)
    return _stat(summary["business_units_represented"], "With at least one employee")


def _employees_by_business_unit(db: Session, user: User, cache: _SummaryCache) -> dict:
    rows = _employee_summary(db, user, cache)["by_business_unit"]
    return {
        "categories": [row["name"] for row in rows],
        "series": [{"name": "Employees", "data": [row["value"] for row in rows]}],
    }


def _employees_by_status(db: Session, user: User, cache: _SummaryCache) -> dict:
    rows = _employee_summary(db, user, cache)["by_status"]
    # Drop empty slices so a pie chart of one status is not mostly labels.
    return {"series": [row for row in rows if row["value"] > 0]}


# ---------------------------------------------------------------------------
# Leave Management (Stage 9)
#
# The same pattern as the employee resolvers above, delegating to the service
# that owns the scoping rule. `leave_service` cannot read a request the caller
# is not allowed to open, so a widget cannot leak one either - the dashboard
# and the list screen are literally the same WHERE clause.
#
# One dashboard definition therefore serves everybody: an employee sees their
# own leave in these tiles, a manager sees their branch's.
# ---------------------------------------------------------------------------


def _leave_summary(db: Session, user: User, cache: _SummaryCache) -> dict:
    if "leave" not in cache:
        cache["leave"] = leave_service.get_dashboard_summary(db, user)
    return cache["leave"]


def _leave_total(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(_leave_summary(db, user, cache)["total_requests"], "In your scope")


def _leave_pending(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(_leave_summary(db, user, cache)["pending"], "Awaiting a decision")


def _leave_approved(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(_leave_summary(db, user, cache)["approved"], "Agreed")


def _leave_rejected(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(_leave_summary(db, user, cache)["rejected"], "Turned down")


def _leave_total_days(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(
        _leave_summary(db, user, cache)["total_days_requested"], "Calendar days"
    )


def _leave_by_type(db: Session, user: User, cache: _SummaryCache) -> dict:
    rows = _leave_summary(db, user, cache)["by_type"]
    return {
        "categories": [row["name"] for row in rows],
        "series": [{"name": "Requests", "data": [row["value"] for row in rows]}],
    }


def _leave_by_status(db: Session, user: User, cache: _SummaryCache) -> dict:
    rows = _leave_summary(db, user, cache)["by_status"]
    # Drop the states nothing has reached yet, so the pie is not mostly
    # zero-sized slices with colliding labels. The numbers themselves are not
    # changed - the service still reports every state.
    return {"series": [row for row in rows if row["value"] > 0]}


def _leave_by_month(db: Session, user: User, cache: _SummaryCache) -> dict:
    rows = _leave_summary(db, user, cache)["by_month"]
    return {
        "categories": [row["name"] for row in rows],
        "series": [{"name": "Requests", "data": [row["value"] for row in rows]}],
    }


# ---------------------------------------------------------------------------
# Attendance and Timesheets (Stage 10)
#
# Same pattern again, delegating to the services that own the scoping rule.
# Neither service can read a record the caller is not allowed to open, so a
# widget cannot leak one either - the dashboard and the list screen beside it
# are literally the same WHERE clause.
# ---------------------------------------------------------------------------


def _attendance_summary(db: Session, user: User, cache: _SummaryCache) -> dict:
    if "attendance" not in cache:
        cache["attendance"] = attendance_service.get_dashboard_summary(db, user)
    return cache["attendance"]


def _attendance_present_today(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(
        _attendance_summary(db, user, cache)["present_today"], "Checked in and out"
    )


def _attendance_incomplete_today(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(
        _attendance_summary(db, user, cache)["incomplete_today"],
        "Checked in, no checkout",
    )


def _attendance_on_leave_today(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(_attendance_summary(db, user, cache)["on_leave_today"], "Away on leave")


def _attendance_total_hours(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(
        _attendance_summary(db, user, cache)["total_worked_hours"], "All recorded days"
    )


def _attendance_average_hours(db: Session, user: User, cache: _SummaryCache) -> dict:
    summary = _attendance_summary(db, user, cache)
    # A stat widget renders whatever `value` holds, so a fractional average is
    # fine here - it is the one figure that would mislead if rounded to a whole
    # number of hours.
    return {"value": summary["average_worked_hours"], "caption": "Hours per day"}


def _attendance_by_status(db: Session, user: User, cache: _SummaryCache) -> dict:
    rows = _attendance_summary(db, user, cache)["by_status"]
    # Drop the statuses nothing has reached, so the pie is not mostly
    # zero-width slices with colliding labels.
    return {"series": [row for row in rows if row["value"] > 0]}


def _attendance_by_day(db: Session, user: User, cache: _SummaryCache) -> dict:
    rows = _attendance_summary(db, user, cache)["by_day"]
    return {
        "categories": [row["name"] for row in rows],
        "series": [{"name": "Days recorded", "data": [row["value"] for row in rows]}],
    }


def _attendance_hours_by_employee(db: Session, user: User, cache: _SummaryCache) -> dict:
    rows = _attendance_summary(db, user, cache)["hours_by_employee"]
    return {
        "categories": [row["name"] for row in rows],
        "series": [{"name": "Hours", "data": [row["value"] for row in rows]}],
    }


def _timesheet_summary(db: Session, user: User, cache: _SummaryCache) -> dict:
    if "timesheets" not in cache:
        cache["timesheets"] = timesheet_service.get_dashboard_summary(db, user)
    return cache["timesheets"]


def _timesheets_total(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(_timesheet_summary(db, user, cache)["total_entries"], "In your scope")


def _timesheets_submitted(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(_timesheet_summary(db, user, cache)["submitted"], "Waiting on a review")


def _timesheets_approved(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(_timesheet_summary(db, user, cache)["approved"], "Signed off")


def _timesheets_approved_hours(db: Session, user: User, cache: _SummaryCache) -> dict:
    summary = _timesheet_summary(db, user, cache)
    return {"value": summary["approved_hours"], "caption": "Approved and counted"}


def _timesheets_by_status(db: Session, user: User, cache: _SummaryCache) -> dict:
    rows = _timesheet_summary(db, user, cache)["by_status"]
    return {"series": [row for row in rows if row["value"] > 0]}


def _timesheets_hours_by_week(db: Session, user: User, cache: _SummaryCache) -> dict:
    rows = _timesheet_summary(db, user, cache)["hours_by_week"]
    return {
        "categories": [row["name"] for row in rows],
        "series": [{"name": "Hours", "data": [row["value"] for row in rows]}],
    }


def _timesheets_hours_by_employee(db: Session, user: User, cache: _SummaryCache) -> dict:
    rows = _timesheet_summary(db, user, cache)["hours_by_employee"]
    return {
        "categories": [row["name"] for row in rows],
        "series": [{"name": "Hours", "data": [row["value"] for row in rows]}],
    }


# ---------------------------------------------------------------------------
# Expenses (Stage 11)
#
# Money, so two things differ from the resolvers above. Amounts are Decimal
# and are converted to float only here, at the very edge, because a chart
# axis is a float either way - the arithmetic that produced the number was
# exact. And every currency figure is reported in the currency the service
# chose; the widget carries `unit: currency` in its metadata so it renders as
# money rather than as a bare count.
# ---------------------------------------------------------------------------


def _expense_summary(db: Session, user: User, cache: _SummaryCache) -> dict:
    if "expenses" not in cache:
        cache["expenses"] = expense_service.get_dashboard_summary(db, user)
    return cache["expenses"]


def _expenses_total(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(_expense_summary(db, user, cache)["total_claims"], "In your scope")


def _expenses_submitted(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(
        _expense_summary(db, user, cache)["submitted"], "Waiting on a decision"
    )


def _expenses_approved(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(_expense_summary(db, user, cache)["approved"], "Signed off")


def _expenses_rejected(db: Session, user: User, cache: _SummaryCache) -> dict:
    return _stat(_expense_summary(db, user, cache)["rejected"], "Turned down")


def _expenses_approved_amount(db: Session, user: User, cache: _SummaryCache) -> dict:
    summary = _expense_summary(db, user, cache)
    return {
        "value": float(summary["approved_amount"]),
        "caption": f"Approved, in {summary['currency']}",
    }


def _expenses_total_amount(db: Session, user: User, cache: _SummaryCache) -> dict:
    summary = _expense_summary(db, user, cache)
    return {
        "value": float(summary["total_amount"]),
        "caption": f"Claimed, in {summary['currency']}",
    }


def _expenses_by_category(db: Session, user: User, cache: _SummaryCache) -> dict:
    rows = _expense_summary(db, user, cache)["by_category"]
    return {
        "categories": [row["name"] for row in rows],
        "series": [{"name": "Amount", "data": [row["value"] for row in rows]}],
    }


def _expenses_by_status(db: Session, user: User, cache: _SummaryCache) -> dict:
    rows = _expense_summary(db, user, cache)["by_status"]
    # Drop the states nothing has reached, so the pie is not mostly
    # zero-width slices with colliding labels.
    return {"series": [row for row in rows if row["value"] > 0]}


def _expenses_by_month(db: Session, user: User, cache: _SummaryCache) -> dict:
    rows = _expense_summary(db, user, cache)["by_month"]
    return {
        "categories": [row["name"] for row in rows],
        "series": [{"name": "Amount", "data": [row["value"] for row in rows]}],
    }


# The registry. A widget's `data_source` string is looked up here; an unknown
# one simply falls back to the widget's stored config rather than erroring, so
# a typo in metadata degrades to sample data instead of breaking the page.
RESOLVERS: dict[str, Callable[[Session, User, _SummaryCache], dict]] = {
    "employees.total": _employees_total,
    "employees.active": _employees_active,
    "employees.inactive": _employees_inactive,
    "employees.business_units": _employees_business_units,
    "employees.by_business_unit": _employees_by_business_unit,
    "employees.by_status": _employees_by_status,
    "leave.total": _leave_total,
    "leave.pending": _leave_pending,
    "leave.approved": _leave_approved,
    "leave.rejected": _leave_rejected,
    "leave.total_days": _leave_total_days,
    "leave.by_type": _leave_by_type,
    "leave.by_status": _leave_by_status,
    "leave.by_month": _leave_by_month,
    "attendance.present_today": _attendance_present_today,
    "attendance.incomplete_today": _attendance_incomplete_today,
    "attendance.on_leave_today": _attendance_on_leave_today,
    "attendance.total_hours": _attendance_total_hours,
    "attendance.average_hours": _attendance_average_hours,
    "attendance.by_status": _attendance_by_status,
    "attendance.by_day": _attendance_by_day,
    "attendance.hours_by_employee": _attendance_hours_by_employee,
    "timesheets.total": _timesheets_total,
    "timesheets.submitted": _timesheets_submitted,
    "timesheets.approved": _timesheets_approved,
    "timesheets.approved_hours": _timesheets_approved_hours,
    "timesheets.by_status": _timesheets_by_status,
    "timesheets.hours_by_week": _timesheets_hours_by_week,
    "timesheets.hours_by_employee": _timesheets_hours_by_employee,
    "expenses.total": _expenses_total,
    "expenses.submitted": _expenses_submitted,
    "expenses.approved": _expenses_approved,
    "expenses.rejected": _expenses_rejected,
    "expenses.approved_amount": _expenses_approved_amount,
    "expenses.total_amount": _expenses_total_amount,
    "expenses.by_category": _expenses_by_category,
    "expenses.by_status": _expenses_by_status,
    "expenses.by_month": _expenses_by_month,
}


def get_dashboard_data(db: Session, user: User, dashboard: Dashboard) -> dict[str, dict]:
    """
    Live values for every widget on a dashboard that declares a data source.

    Returns a map of widget code to the config-shaped data the frontend merges
    over the widget's stored config. Widgets without a data source are absent
    from the map and keep their sample values.
    """
    cache: _SummaryCache = {}
    data: dict[str, dict] = {}

    for widget in metadata_service.get_widgets_for_dashboard(db, dashboard):
        source = (widget.config_json or {}).get("data_source")
        resolver = RESOLVERS.get(source) if source else None
        if resolver is None:
            continue
        data[widget.code] = resolver(db, user, cache)

    return data
