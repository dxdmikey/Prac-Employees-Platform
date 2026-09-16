"""
Who may see whose records, for the employee-facing applications.

Three applications now ask the same question. Leave, Attendance and Timesheets
are all *self-service*: an ordinary employee can open them, so "what may I
see?" cannot simply be "everything in my business units" - that would let one
colleague read another's leave or attendance. Equally it cannot be "only my
own", because a manager has to approve.

The rule, in one sentence:

    You can always see your own records.
    You can see somebody else's only if you hold the APPROVE permission AND
    their employee record sits inside your business-unit scope.

Both halves are needed, and neither implies the other:

  * jane (EMPLOYEE, Department 1) has scope over Department 1 but no APPROVE
    permission, so she sees only her own records - not her colleagues'.
  * raj (MANAGER, Branch 1) has APPROVE, so he sees everyone in Branch 1 and
    the departments beneath it - and nobody in Branch 2.

Nothing here decides anything itself. The permission comes from
`rbac_service`, the units come from `business_unit_service` and its recursive
CTE, and this module only combines their answers into one SQL condition. That
is the point: one combination, used three times, rather than three copies that
can drift apart.

Contrast with `employee_service`, which scopes by business unit alone. That is
correct there because Employee Management is an HR application an ordinary
employee cannot open at all, so there is no "my own record" case to allow.
"""

from sqlalchemy import ColumnElement, false, or_, select
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.user import User
from app.services import business_unit_service, rbac_service

# The permission that turns "my own records" into "my team's records".
#
# A permission code, not a role name. Which roles hold APPROVE is metadata, so
# granting a new role the ability to review timesheets is an INSERT rather than
# a change here.
APPROVER_PERMISSION = "APPROVE"


def get_own_employee(db: Session, user: User) -> Employee | None:
    """
    The employee record linked to this login, if there is one.

    Most employees have no login and some logins have no employee record - the
    platform admin, for instance. Both are normal, which is why this returns
    None rather than raising.
    """
    return db.scalar(select(Employee).where(Employee.user_id == user.id))


def can_approve(db: Session, user: User) -> bool:
    """Does this user hold the permission that lets them see other people's records?"""
    return rbac_service.has_permission(db, user, APPROVER_PERMISSION)


def visible_employee_filter(
    db: Session, user: User, employee_id_column
) -> ColumnElement[bool]:
    """
    A SQL condition restricting any table that references `employees.id`.

    Pass the table's employee_id column and apply the result with `.where()`:

        query.where(visible_employee_filter(db, user, Attendance.employee_id))

    Returning a condition rather than a finished query is deliberate. It keeps
    this module ignorant of attendance, timesheets and leave, and it lets each
    service build its own base query with its own eager-loading - while still
    being unable to write a different access rule.
    """
    conditions = []

    own = get_own_employee(db, user)
    if own is not None:
        conditions.append(employee_id_column == own.id)

    if can_approve(db, user):
        visible_units = business_unit_service.get_user_visible_business_unit_ids(
            db, user
        )
        # An approver with no business-unit assignment gets no second clause at
        # all. No assignment means nothing, never everything.
        if visible_units:
            conditions.append(
                employee_id_column.in_(
                    select(Employee.id).where(
                        Employee.business_unit_id.in_(visible_units)
                    )
                )
            )

    # Neither their own record nor any scope: they see nothing. `false()`
    # rather than a Python False, so SQLAlchemy renders a real SQL predicate
    # and the query returns no rows instead of every row.
    return or_(*conditions) if conditions else false()
