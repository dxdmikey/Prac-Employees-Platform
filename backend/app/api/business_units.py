"""
Business unit endpoints - the organisation hierarchy and who sits where.

Two groups, protected differently:

  * **Management** (the tree itself, and user assignments) is platform
    administration. It reuses the existing metadata-driven guards -
    USER_MANAGEMENT for the organisation structure, USER_ROLE_MANAGEMENT for
    assigning units to people, mirroring how roles are assigned. No new
    application was invented; the platform still has exactly eight.

  * **Self-service** (`/api/access/business-units` and the access check) is
    open to any signed-in user, because it only ever describes that caller.

The access check at the bottom is the demonstration that authorisation is now
two questions - what may you do, and where.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_application, require_permission
from app.db.database import get_db
from app.models.business_unit import BusinessUnit
from app.models.user import User
from app.schemas.business_unit import (
    AssignBusinessUnitRequest,
    BusinessUnitAccessResponse,
    BusinessUnitCreateRequest,
    BusinessUnitNode,
    BusinessUnitResponse,
    BusinessUnitTypeResponse,
    BusinessUnitUpdateRequest,
    MyBusinessUnitsResponse,
)
from app.services import business_unit_service
from app.services.business_unit_service import BusinessUnitError

router = APIRouter(tags=["business-units"])

# Guards, named once so the intent is readable at each endpoint.
manage_organisation = Depends(require_application("USER_MANAGEMENT"))
manage_assignments = Depends(require_application("USER_ROLE_MANAGEMENT"))


def _get_unit_or_404(db: Session, business_unit_id: int) -> BusinessUnit:
    unit = db.get(BusinessUnit, business_unit_id)
    if unit is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Business unit not found"
        )
    return unit


def _get_user_or_404(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user


def _bad_request(exc: BusinessUnitError) -> HTTPException:
    """A rejected hierarchy operation is the caller's mistake, so 400."""
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@router.get(
    "/api/business-unit-types",
    response_model=list[BusinessUnitTypeResponse],
    dependencies=[manage_organisation],
)
def list_business_unit_types(
    db: Session = Depends(get_db),
) -> list[BusinessUnitTypeResponse]:
    """Headquarters, Company, Branch, Department - as data, not an enum."""
    return [
        BusinessUnitTypeResponse.model_validate(t)
        for t in business_unit_service.list_business_unit_types(db)
    ]


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------


@router.get(
    "/api/business-units",
    response_model=list[BusinessUnitResponse],
    dependencies=[manage_organisation],
)
def list_business_units(db: Session = Depends(get_db)) -> list[BusinessUnitResponse]:
    """Every business unit as a flat list."""
    return [
        BusinessUnitResponse.model_validate(u)
        for u in business_unit_service.list_business_units(db)
    ]


@router.get(
    "/api/business-units/tree",
    response_model=list[BusinessUnitNode],
    dependencies=[manage_organisation],
)
def read_business_unit_tree(db: Session = Depends(get_db)) -> list[BusinessUnitNode]:
    """
    The whole organisation, nested.

    Declared before /api/business-units/{id} on purpose: FastAPI matches routes
    in order, and "tree" would otherwise be read as an id.
    """
    return [BusinessUnitNode(**node) for node in business_unit_service.build_tree(db)]


@router.post(
    "/api/business-units",
    response_model=BusinessUnitResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[manage_organisation],
)
def create_business_unit(
    payload: BusinessUnitCreateRequest, db: Session = Depends(get_db)
) -> BusinessUnitResponse:
    """Add a unit. Omit parent_id to create a new root."""
    try:
        unit = business_unit_service.create_business_unit(
            db,
            code=payload.code,
            name=payload.name,
            business_unit_type_id=payload.business_unit_type_id,
            parent_id=payload.parent_id,
            description=payload.description,
        )
    except BusinessUnitError as exc:
        raise _bad_request(exc) from exc
    return BusinessUnitResponse.model_validate(unit)


@router.put(
    "/api/business-units/{business_unit_id}",
    response_model=BusinessUnitResponse,
    dependencies=[manage_organisation],
)
def update_business_unit(
    business_unit_id: int,
    payload: BusinessUnitUpdateRequest,
    db: Session = Depends(get_db),
) -> BusinessUnitResponse:
    """
    Change a unit. Moving it is allowed, but self-parenting and cycles are
    refused with a 400 explaining why.
    """
    unit = _get_unit_or_404(db, business_unit_id)
    # model_fields_set tells us which keys the caller actually sent, so an
    # omitted parent_id leaves the unit where it is instead of orphaning it.
    reparent = "parent_id" in payload.model_fields_set

    try:
        unit = business_unit_service.update_business_unit(
            db,
            unit,
            name=payload.name,
            business_unit_type_id=payload.business_unit_type_id,
            parent_id=payload.parent_id,
            description=payload.description,
            is_active=payload.is_active,
            reparent=reparent,
        )
    except BusinessUnitError as exc:
        raise _bad_request(exc) from exc
    return BusinessUnitResponse.model_validate(unit)


@router.delete(
    "/api/business-units/{business_unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[manage_organisation],
)
def delete_business_unit(
    business_unit_id: int, db: Session = Depends(get_db)
) -> None:
    """Delete a unit. Refused while anything still sits beneath it."""
    unit = _get_unit_or_404(db, business_unit_id)
    try:
        business_unit_service.delete_business_unit(db, unit)
    except BusinessUnitError as exc:
        raise _bad_request(exc) from exc


# ---------------------------------------------------------------------------
# User assignments
# ---------------------------------------------------------------------------


@router.get(
    "/api/users/{user_id}/business-units",
    response_model=list[BusinessUnitResponse],
    dependencies=[manage_assignments],
)
def list_user_business_units(
    user_id: int, db: Session = Depends(get_db)
) -> list[BusinessUnitResponse]:
    """The units a user is directly assigned to."""
    user = _get_user_or_404(db, user_id)
    return [
        BusinessUnitResponse.model_validate(u)
        for u in business_unit_service.get_user_business_units(db, user)
    ]


@router.post(
    "/api/users/{user_id}/business-units",
    response_model=list[BusinessUnitResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[manage_assignments],
)
def assign_user_business_unit(
    user_id: int,
    payload: AssignBusinessUnitRequest,
    db: Session = Depends(get_db),
) -> list[BusinessUnitResponse]:
    """Assign a unit, and return the user's complete new list."""
    user = _get_user_or_404(db, user_id)
    unit = _get_unit_or_404(db, payload.business_unit_id)
    business_unit_service.assign_business_unit_to_user(db, user, unit)
    return [
        BusinessUnitResponse.model_validate(u)
        for u in business_unit_service.get_user_business_units(db, user)
    ]


@router.delete(
    "/api/users/{user_id}/business-units/{business_unit_id}",
    response_model=list[BusinessUnitResponse],
    dependencies=[manage_assignments],
)
def remove_user_business_unit(
    user_id: int, business_unit_id: int, db: Session = Depends(get_db)
) -> list[BusinessUnitResponse]:
    """Remove an assignment, and return what remains."""
    user = _get_user_or_404(db, user_id)
    unit = _get_unit_or_404(db, business_unit_id)
    business_unit_service.remove_business_unit_from_user(db, user, unit)
    return [
        BusinessUnitResponse.model_validate(u)
        for u in business_unit_service.get_user_business_units(db, user)
    ]


# ---------------------------------------------------------------------------
# Self-service: my own scope
# ---------------------------------------------------------------------------


@router.get("/api/access/business-units", response_model=MyBusinessUnitsResponse)
def read_my_business_units(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MyBusinessUnitsResponse:
    """
    My organisational scope.

    `assigned` is what an administrator gave me. `visible` is that plus every
    unit beneath it - the difference between the two *is* the inheritance rule.
    """
    return MyBusinessUnitsResponse(
        assigned=[
            BusinessUnitResponse.model_validate(u)
            for u in business_unit_service.get_user_business_units(db, current_user)
        ],
        visible=[
            BusinessUnitResponse.model_validate(u)
            for u in business_unit_service.get_user_visible_business_units(
                db, current_user
            )
        ],
    )


@router.get(
    "/api/business-units/{business_unit_id}/access-check",
    response_model=BusinessUnitAccessResponse,
)
def check_business_unit_access(
    business_unit_id: int,
    # Question 1 - WHAT: does this user hold the VIEW permission, through any
    # of their roles? Answered by the existing RBAC dependency, unchanged.
    current_user: User = Depends(require_permission("VIEW")),
    db: Session = Depends(get_db),
) -> BusinessUnitAccessResponse:
    """
    The demonstration endpoint: both halves of authorisation, in order.

        1. RBAC       - do you hold the VIEW permission?        -> 403 if not
        2. BU scope   - is this unit yours, or beneath yours?   -> 403 if not

    Failing either is a 403. Both must pass, which is what "RBAC **plus**
    business-unit scope" means in practice.
    """
    unit = _get_unit_or_404(db, business_unit_id)

    # Question 2 - WHERE.
    if not business_unit_service.can_access_business_unit(db, current_user, unit.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"You have the VIEW permission, but {unit.name} is outside your "
                "organisational scope."
            ),
        )

    assigned = {u.id for u in current_user.business_units}
    return BusinessUnitAccessResponse(
        business_unit_id=unit.id,
        business_unit_code=unit.code,
        business_unit_name=unit.name,
        access=True,
        reason=(
            "directly assigned"
            if unit.id in assigned
            else "inherited from a business unit above it"
        ),
    )
