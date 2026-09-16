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
from app.services import employee_service, leave_service, metadata_service

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
