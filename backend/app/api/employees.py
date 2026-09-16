"""
Employee Management endpoints - the first real business application.

Authorisation is two questions, both already built:

  * **RBAC** - `require_application("EMPLOYEE_MANAGEMENT")` decides who may use
    this application at all, and `require_permission(...)` decides who may
    write. An EMPLOYEE role has neither, so every endpoint here is closed to
    them.
  * **Business-unit scope** - handled inside `employee_service`, which never
    reads employees without narrowing to the caller's visible units.

Nothing here re-implements either. The endpoints translate HTTP to service
calls and back.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_application, require_permission
from app.db.database import get_db
from app.models.employee import EMPLOYMENT_STATUSES, Employee
from app.models.user import User
from app.schemas.employee import (
    EmployeeCreateRequest,
    EmployeeDashboardResponse,
    EmployeeListResponse,
    EmployeeResponse,
    EmployeeUpdateRequest,
    RelatedRef,
)
from app.services import employee_service
from app.services.employee_service import EmployeeError, EmployeeNotVisible

router = APIRouter(prefix="/api/employees", tags=["employees"])

# Opening the application at all. Applied to every route in this router.
open_application = Depends(require_application("EMPLOYEE_MANAGEMENT"))


def _row(employee: Employee) -> EmployeeResponse:
    return EmployeeResponse(
        id=employee.id,
        employee_code=employee.employee_code,
        first_name=employee.first_name,
        last_name=employee.last_name,
        full_name=employee.full_name,
        email=employee.email,
        phone=employee.phone,
        date_of_joining=employee.date_of_joining,
        job_title=employee.job_title,
        employment_status=employee.employment_status,
        business_unit=RelatedRef(
            id=employee.business_unit.id, name=employee.business_unit.name
        ),
        manager=(
            RelatedRef(id=employee.manager.id, name=employee.manager.full_name)
            if employee.manager
            else None
        ),
        user_id=employee.user_id,
        created_at=employee.created_at,
    )


def _http(exc: EmployeeError) -> HTTPException:
    """
    Scope failures are 403; everything else the caller got wrong is 400.

    A record outside the caller's scope is reported as 404 by the service
    wording ("no employee with that id is available to you") but returned as
    403 here, because the caller does have the application - they simply do
    not have that part of the organisation.
    """
    code = (
        status.HTTP_403_FORBIDDEN
        if isinstance(exc, EmployeeNotVisible)
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=str(exc))


# ---------------------------------------------------------------------------
# Dashboard - declared before /{employee_id} so "dashboard" is not read as an id
# ---------------------------------------------------------------------------


@router.get(
    "/dashboard",
    response_model=EmployeeDashboardResponse,
    dependencies=[open_application],
)
def read_employee_dashboard(
    current_user: User = Depends(require_permission("VIEW")),
    db: Session = Depends(get_db),
) -> EmployeeDashboardResponse:
    """Real aggregated figures, narrowed to what this user may see."""
    return EmployeeDashboardResponse(
        **employee_service.get_dashboard_summary(db, current_user)
    )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


@router.get("", response_model=EmployeeListResponse, dependencies=[open_application])
def list_employees(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=employee_service.MAX_PAGE_SIZE),
    search: str | None = Query(None, max_length=100),
    business_unit_id: int | None = Query(None, gt=0),
    employment_status: str | None = Query(None),
    manager_id: int | None = Query(None, gt=0),
    current_user: User = Depends(require_permission("VIEW")),
    db: Session = Depends(get_db),
) -> EmployeeListResponse:
    """One page of employees, filtered and scoped."""
    if employment_status and employment_status not in EMPLOYMENT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"employment_status must be one of {', '.join(EMPLOYMENT_STATUSES)}.",
        )

    rows, total = employee_service.list_employees(
        db,
        current_user,
        page=page,
        page_size=page_size,
        search=search,
        business_unit_id=business_unit_id,
        employment_status=employment_status,
        manager_id=manager_id,
    )

    return EmployeeListResponse(
        items=[_row(employee) for employee in rows],
        total=total,
        page=page,
        page_size=page_size,
        # Ceiling division without importing math.
        total_pages=max(1, -(-total // page_size)),
    )


@router.get(
    "/{employee_id}", response_model=EmployeeResponse, dependencies=[open_application]
)
def read_employee(
    employee_id: int,
    current_user: User = Depends(require_permission("VIEW")),
    db: Session = Depends(get_db),
) -> EmployeeResponse:
    try:
        return _row(employee_service.get_visible_employee(db, current_user, employee_id))
    except EmployeeError as exc:
        raise _http(exc) from exc


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=EmployeeResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[open_application],
)
def create_employee(
    payload: EmployeeCreateRequest,
    # CREATE, not a role name - HR holds it, MANAGER does not.
    current_user: User = Depends(require_permission("CREATE")),
    db: Session = Depends(get_db),
) -> EmployeeResponse:
    """
    Create an employee.

    Every id in the body is re-checked against the caller's scope. An id from
    the frontend is a request, not a fact.
    """
    try:
        employee = employee_service.create_employee(
            db, current_user, payload.model_dump()
        )
    except EmployeeError as exc:
        raise _http(exc) from exc
    return _row(employee)


@router.put(
    "/{employee_id}",
    response_model=EmployeeResponse,
    dependencies=[open_application],
)
def update_employee(
    employee_id: int,
    payload: EmployeeUpdateRequest,
    current_user: User = Depends(require_permission("EDIT")),
    db: Session = Depends(get_db),
) -> EmployeeResponse:
    """
    Update an employee.

    There is no DELETE. Set employment_status to INACTIVE instead - a deleted
    record would take its reporting lines and history with it.
    """
    try:
        employee = employee_service.get_visible_employee(db, current_user, employee_id)
        # exclude_unset so an omitted field is left alone rather than nulled.
        updated = employee_service.update_employee(
            db, current_user, employee, payload.model_dump(exclude_unset=True)
        )
    except EmployeeError as exc:
        raise _http(exc) from exc
    return _row(updated)
