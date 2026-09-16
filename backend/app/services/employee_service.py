"""
Employee Management business logic.

The single most important thing in this module is that **every read is scoped**.
There is no function here that returns employees without first narrowing to the
business units the caller may see, and that narrowing is not reimplemented -
it calls `business_unit_service`, the same code Stage 5 built and tested.

The scope rule, restated: a user assigned Company 1 sees Company 1 and every
unit beneath it. A user assigned Branch 1 sees Branch 1 and its departments,
and never Company 1 above it.
"""

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.business_unit import BusinessUnit
from app.models.employee import EMPLOYMENT_STATUSES, Employee
from app.models.user import User
from app.services import business_unit_service


class EmployeeError(Exception):
    """A request the business rules refuse. The API turns it into a 400/403."""


class EmployeeNotVisible(EmployeeError):
    """The record exists but is outside the caller's business-unit scope."""


MAX_PAGE_SIZE = 100


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def _visible_business_unit_ids(db: Session, user: User) -> set[int]:
    """
    The business units this user may see, reusing the Stage 5 service.

    Note there is no "super admin sees everything" branch. A Super Admin sees
    the whole organisation because they are assigned Headquarters and the
    hierarchy does the rest - scope is data, not a role name.
    """
    return business_unit_service.get_user_visible_business_unit_ids(db, user)


def _scoped_query(db: Session, user: User) -> Select:
    """
    The base query for every employee read.

    Nothing in this module queries `employees` without going through here, so
    a future filter or endpoint cannot accidentally skip the scope check.
    """
    visible_ids = _visible_business_unit_ids(db, user)
    query = select(Employee).options(
        selectinload(Employee.business_unit),
        selectinload(Employee.manager),
    )
    if not visible_ids:
        # No assignment means no employees - not "all employees".
        return query.where(False)
    return query.where(Employee.business_unit_id.in_(visible_ids))


def get_visible_employee(db: Session, user: User, employee_id: int) -> Employee:
    """One employee, if the caller may see them."""
    employee = db.scalar(_scoped_query(db, user).where(Employee.id == employee_id))
    if employee is None:
        raise EmployeeNotVisible("No employee with that id is available to you.")
    return employee


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


def list_employees(
    db: Session,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    business_unit_id: int | None = None,
    employment_status: str | None = None,
    manager_id: int | None = None,
) -> tuple[list[Employee], int]:
    """
    A page of employees the caller may see, plus the total that matched.

    Paging happens in the database with LIMIT/OFFSET. The browser never
    receives the whole table, which matters as soon as the dataset is real.
    """
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)

    query = _scoped_query(db, user)

    if search:
        # A simple case-insensitive contains across the fields someone would
        # actually type. Not full-text search - that would be premature here.
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(
                Employee.first_name.ilike(pattern),
                Employee.last_name.ilike(pattern),
                Employee.employee_code.ilike(pattern),
                Employee.email.ilike(pattern),
                Employee.job_title.ilike(pattern),
            )
        )

    if business_unit_id is not None:
        # Filtering by a unit the caller cannot see must narrow the results to
        # nothing, never widen them - the scope clause above still applies.
        query = query.where(Employee.business_unit_id == business_unit_id)

    if employment_status:
        query = query.where(Employee.employment_status == employment_status)

    if manager_id is not None:
        query = query.where(Employee.manager_id == manager_id)

    # Count before paging, so "of 23" is the number of matches and not the
    # size of the current page.
    total = db.scalar(
        select(func.count()).select_from(query.order_by(None).subquery())
    )

    rows = list(
        db.scalars(
            query.order_by(Employee.employee_code)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return rows, int(total or 0)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _check_business_unit(db: Session, user: User, business_unit_id: int) -> None:
    """
    The unit must exist AND be one the caller may see.

    This is what stops a manager creating or moving an employee into a part of
    the organisation they have no business touching, however they got the id.
    """
    if db.get(BusinessUnit, business_unit_id) is None:
        raise EmployeeError(f"No business unit with id {business_unit_id}.")
    if not business_unit_service.can_access_business_unit(db, user, business_unit_id):
        raise EmployeeError(
            "That business unit is outside your organisational scope."
        )


def _check_manager(
    db: Session, user: User, manager_id: int | None, employee_id: int | None
) -> None:
    """The manager must exist, be visible, and not be the employee themselves."""
    if manager_id is None:
        return
    if employee_id is not None and manager_id == employee_id:
        raise EmployeeError("An employee cannot be their own manager.")

    manager = db.scalar(_scoped_query(db, user).where(Employee.id == manager_id))
    if manager is None:
        raise EmployeeError("No manager with that id is available to you.")


def _check_unique(db: Session, code: str | None, email: str | None) -> None:
    if code and db.scalar(select(Employee).where(Employee.employee_code == code)):
        raise EmployeeError(f"An employee with code {code} already exists.")
    if email and db.scalar(select(Employee).where(Employee.email == email)):
        raise EmployeeError(f"An employee with email {email} already exists.")


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def create_employee(db: Session, user: User, data: dict) -> Employee:
    """Create an employee, after checking every id the caller supplied."""
    _check_unique(db, data.get("employee_code"), data.get("email"))
    _check_business_unit(db, user, data["business_unit_id"])
    _check_manager(db, user, data.get("manager_id"), None)

    employee = Employee(**data)
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def update_employee(
    db: Session, user: User, employee: Employee, changes: dict
) -> Employee:
    """Update an employee. Only supplied fields are touched."""
    if "email" in changes and changes["email"] != employee.email:
        _check_unique(db, None, changes["email"])

    if "business_unit_id" in changes:
        _check_business_unit(db, user, changes["business_unit_id"])

    if "manager_id" in changes:
        _check_manager(db, user, changes["manager_id"], employee.id)

    if changes.get("employment_status") not in (None, *EMPLOYMENT_STATUSES):
        raise EmployeeError("Unknown employment status.")

    for field, value in changes.items():
        setattr(employee, field, value)

    db.commit()
    db.refresh(employee)
    return employee


# ---------------------------------------------------------------------------
# Dashboard aggregation
# ---------------------------------------------------------------------------


def get_dashboard_summary(db: Session, user: User) -> dict:
    """
    Employee figures for the caller's scope, straight from PostgreSQL.

    The aggregation runs against the same scoped set as the list, so an HR user
    in Company 1 gets Company 1 totals - the dashboard cannot quietly reveal
    headcount from a part of the organisation the list would hide.
    """
    visible_ids = _visible_business_unit_ids(db, user)
    if not visible_ids:
        return {
            "total_employees": 0,
            "active_employees": 0,
            "inactive_employees": 0,
            "on_leave_employees": 0,
            "business_units_represented": 0,
            "by_business_unit": [],
            "by_status": [],
        }

    scope = Employee.business_unit_id.in_(visible_ids)

    # One grouped query for the status split, rather than one query per status.
    status_counts = {
        status: count
        for status, count in db.execute(
            select(Employee.employment_status, func.count())
            .where(scope)
            .group_by(Employee.employment_status)
        )
    }

    by_business_unit = [
        {"name": name, "value": count}
        for name, count in db.execute(
            select(BusinessUnit.name, func.count(Employee.id))
            .join(Employee, Employee.business_unit_id == BusinessUnit.id)
            .where(scope)
            .group_by(BusinessUnit.name)
            .order_by(func.count(Employee.id).desc(), BusinessUnit.name)
        )
    ]

    return {
        "total_employees": sum(status_counts.values()),
        "active_employees": status_counts.get("ACTIVE", 0),
        "inactive_employees": status_counts.get("INACTIVE", 0),
        "on_leave_employees": status_counts.get("ON_LEAVE", 0),
        "business_units_represented": len(by_business_unit),
        "by_business_unit": by_business_unit,
        # Listed in a fixed order so the chart colours stay stable between
        # loads even when a status has no rows.
        "by_status": [
            {"name": status.replace("_", " ").title(),
             "value": status_counts.get(status, 0)}
            for status in EMPLOYMENT_STATUSES
        ],
    }
