"""
RBAC management endpoints - reading and changing the access metadata itself.

Protection here is metadata-driven. Each endpoint requires access to the
platform-admin application it belongs to:

    /api/users            -> USER_MANAGEMENT
    /api/roles            -> ROLE_MANAGEMENT
    /api/permissions      -> ROLE_MANAGEMENT
    /api/applications     -> ROLE_MANAGEMENT
    /api/users/*/roles    -> USER_ROLE_MANAGEMENT

No endpoint checks for a role called SUPER_ADMIN. A Super Admin gets through
because the seed links that role to those applications; anyone else is refused
by the same rule. Granting a new person administrative access is therefore an
INSERT, not a code change.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_application, require_permission
from app.db.database import get_db
from app.models.application import Application
from app.models.permission import Permission
from app.models.role import Role
from app.models.screen import Screen
from app.models.user import User
from app.schemas.rbac import (
    ApplicationResponse,
    AssignApplicationRequest,
    AssignPermissionRequest,
    AssignRoleRequest,
    AssignScreenRequest,
    PermissionResponse,
    RoleResponse,
    RoleScreenResponse,
    UserWithRolesResponse,
)
from app.services import rbac_service

router = APIRouter(tags=["rbac"])


# --- small helpers ----------------------------------------------------------


def _get_or_404(db: Session, model, item_id: int, label: str):
    """Fetch any metadata row by id, or raise a tidy 404."""
    item = db.get(model, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} not found"
        )
    return item


def _application_rows(role: Role) -> list[ApplicationResponse]:
    return [
        ApplicationResponse.model_validate(application)
        for application in sorted(role.applications, key=lambda a: a.display_order)
    ]


def _role_screen_rows(role: Role) -> list[RoleScreenResponse]:
    """A role's screens, each labelled with the application it belongs to."""
    return [
        RoleScreenResponse(
            id=screen.id,
            code=screen.code,
            name=screen.name,
            application_code=screen.application.code,
            application_name=screen.application.name,
        )
        for screen in sorted(
            role.screens, key=lambda s: (s.application.display_order, s.display_order)
        )
    ]


# --- reading the metadata ---------------------------------------------------


@router.get(
    "/api/roles",
    response_model=list[RoleResponse],
    dependencies=[Depends(require_application("ROLE_MANAGEMENT"))],
)
def list_roles(db: Session = Depends(get_db)) -> list[RoleResponse]:
    """Every role defined on the platform."""
    roles = db.scalars(select(Role).order_by(Role.code))
    return [RoleResponse.model_validate(role) for role in roles]


@router.get(
    "/api/permissions",
    response_model=list[PermissionResponse],
    dependencies=[Depends(require_application("ROLE_MANAGEMENT"))],
)
def list_permissions(db: Session = Depends(get_db)) -> list[PermissionResponse]:
    """Every permission defined on the platform."""
    permissions = db.scalars(select(Permission).order_by(Permission.code))
    return [PermissionResponse.model_validate(p) for p in permissions]


@router.get(
    "/api/applications",
    response_model=list[ApplicationResponse],
    dependencies=[Depends(require_application("ROLE_MANAGEMENT"))],
)
def list_applications(db: Session = Depends(get_db)) -> list[ApplicationResponse]:
    """
    Every application defined on the platform.

    This is the administrator's full catalogue. It is not the same as
    /api/access/me, which returns only the applications the caller may open.
    """
    applications = db.scalars(
        select(Application).order_by(Application.display_order, Application.name)
    )
    return [ApplicationResponse.model_validate(a) for a in applications]


@router.get(
    "/api/users",
    response_model=list[UserWithRolesResponse],
    dependencies=[Depends(require_application("USER_MANAGEMENT"))],
)
def list_users(db: Session = Depends(get_db)) -> list[UserWithRolesResponse]:
    """
    Every user, with their roles.

    selectinload fetches all the roles in one extra query instead of one query
    per user - the standard fix for the "N+1 queries" problem.
    """
    users = db.scalars(
        select(User)
        .options(selectinload(User.roles), selectinload(User.business_units))
        .order_by(User.username)
    )
    return [UserWithRolesResponse.model_validate(user) for user in users]


# --- user -> role assignment ------------------------------------------------


@router.get(
    "/api/users/{user_id}/roles",
    response_model=list[RoleResponse],
    dependencies=[Depends(require_application("USER_ROLE_MANAGEMENT"))],
)
def list_user_roles(user_id: int, db: Session = Depends(get_db)) -> list[RoleResponse]:
    """The roles currently assigned to one user."""
    user = _get_or_404(db, User, user_id, "User")
    return [RoleResponse.model_validate(role) for role in user.roles]


@router.post(
    "/api/users/{user_id}/roles",
    response_model=list[RoleResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_application("USER_ROLE_MANAGEMENT"))],
)
def assign_user_role(
    user_id: int,
    payload: AssignRoleRequest,
    db: Session = Depends(get_db),
) -> list[RoleResponse]:
    """
    Give a user a role, and return their new complete role list.

    Returning the full list means the admin screen can redraw from the
    response instead of making a second request.
    """
    user = _get_or_404(db, User, user_id, "User")
    role = _get_or_404(db, Role, payload.role_id, "Role")
    rbac_service.assign_role_to_user(db, user, role)
    return [RoleResponse.model_validate(r) for r in user.roles]


@router.delete(
    "/api/users/{user_id}/roles/{role_id}",
    response_model=list[RoleResponse],
    dependencies=[Depends(require_application("USER_ROLE_MANAGEMENT"))],
)
def remove_user_role(
    user_id: int,
    role_id: int,
    db: Session = Depends(get_db),
) -> list[RoleResponse]:
    """Take a role away from a user, and return their remaining roles."""
    user = _get_or_404(db, User, user_id, "User")
    role = _get_or_404(db, Role, role_id, "Role")
    rbac_service.remove_role_from_user(db, user, role)
    return [RoleResponse.model_validate(r) for r in user.roles]


# --- what a role is made of -------------------------------------------------
#
# Three pairs of endpoints with one shape: POST grants, DELETE revokes, and
# each returns the role's new complete list so the caller can redraw from the
# response. Repeating a grant or a revoke is deliberately not an error.


@router.get(
    "/api/roles/{role_id}/permissions",
    response_model=list[PermissionResponse],
    dependencies=[Depends(require_application("ROLE_MANAGEMENT"))],
)
def list_role_permissions(
    role_id: int, db: Session = Depends(get_db)
) -> list[PermissionResponse]:
    """Which permissions a role carries."""
    role = _get_or_404(db, Role, role_id, "Role")
    return [PermissionResponse.model_validate(p) for p in role.permissions]


@router.post(
    "/api/roles/{role_id}/permissions",
    response_model=list[PermissionResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_application("ROLE_MANAGEMENT"))],
)
def grant_role_permission(
    role_id: int, payload: AssignPermissionRequest, db: Session = Depends(get_db)
) -> list[PermissionResponse]:
    """Grant a permission to a role."""
    role = _get_or_404(db, Role, role_id, "Role")
    permission = _get_or_404(db, Permission, payload.permission_id, "Permission")
    rbac_service.set_role_permission(db, role, permission, granted=True)
    return [PermissionResponse.model_validate(p) for p in role.permissions]


@router.delete(
    "/api/roles/{role_id}/permissions/{permission_id}",
    response_model=list[PermissionResponse],
    dependencies=[Depends(require_application("ROLE_MANAGEMENT"))],
)
def revoke_role_permission(
    role_id: int, permission_id: int, db: Session = Depends(get_db)
) -> list[PermissionResponse]:
    """Revoke a permission from a role."""
    role = _get_or_404(db, Role, role_id, "Role")
    permission = _get_or_404(db, Permission, permission_id, "Permission")
    rbac_service.set_role_permission(db, role, permission, granted=False)
    return [PermissionResponse.model_validate(p) for p in role.permissions]


@router.get(
    "/api/roles/{role_id}/applications",
    response_model=list[ApplicationResponse],
    dependencies=[Depends(require_application("ROLE_MANAGEMENT"))],
)
def list_role_applications(
    role_id: int, db: Session = Depends(get_db)
) -> list[ApplicationResponse]:
    """Which applications a role can open."""
    return _application_rows(_get_or_404(db, Role, role_id, "Role"))


@router.post(
    "/api/roles/{role_id}/applications",
    response_model=list[ApplicationResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_application("ROLE_MANAGEMENT"))],
)
def grant_role_application(
    role_id: int, payload: AssignApplicationRequest, db: Session = Depends(get_db)
) -> list[ApplicationResponse]:
    """Give a role access to an application."""
    role = _get_or_404(db, Role, role_id, "Role")
    application = _get_or_404(db, Application, payload.application_id, "Application")
    rbac_service.set_role_application(db, role, application, granted=True)
    return _application_rows(role)


@router.delete(
    "/api/roles/{role_id}/applications/{application_id}",
    response_model=list[ApplicationResponse],
    dependencies=[Depends(require_application("ROLE_MANAGEMENT"))],
)
def revoke_role_application(
    role_id: int, application_id: int, db: Session = Depends(get_db)
) -> list[ApplicationResponse]:
    """Remove a role's access to an application."""
    role = _get_or_404(db, Role, role_id, "Role")
    application = _get_or_404(db, Application, application_id, "Application")
    rbac_service.set_role_application(db, role, application, granted=False)
    return _application_rows(role)


@router.get(
    "/api/roles/{role_id}/screens",
    response_model=list[RoleScreenResponse],
    dependencies=[Depends(require_application("ROLE_MANAGEMENT"))],
)
def list_role_screens(
    role_id: int, db: Session = Depends(get_db)
) -> list[RoleScreenResponse]:
    """
    Which screens a role can open, with the application each belongs to.

    Screens are only meaningful next to their application - "Timesheet" alone
    does not say which app it lives in.
    """
    return _role_screen_rows(_get_or_404(db, Role, role_id, "Role"))


@router.post(
    "/api/roles/{role_id}/screens",
    response_model=list[RoleScreenResponse],
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_application("ROLE_MANAGEMENT"))],
)
def grant_role_screen(
    role_id: int, payload: AssignScreenRequest, db: Session = Depends(get_db)
) -> list[RoleScreenResponse]:
    """Give a role access to a screen."""
    role = _get_or_404(db, Role, role_id, "Role")
    screen = _get_or_404(db, Screen, payload.screen_id, "Screen")
    rbac_service.set_role_screen(db, role, screen, granted=True)
    return _role_screen_rows(role)


@router.delete(
    "/api/roles/{role_id}/screens/{screen_id}",
    response_model=list[RoleScreenResponse],
    dependencies=[Depends(require_application("ROLE_MANAGEMENT"))],
)
def revoke_role_screen(
    role_id: int, screen_id: int, db: Session = Depends(get_db)
) -> list[RoleScreenResponse]:
    """Remove a role's access to a screen."""
    role = _get_or_404(db, Role, role_id, "Role")
    screen = _get_or_404(db, Screen, screen_id, "Screen")
    rbac_service.set_role_screen(db, role, screen, granted=False)
    return _role_screen_rows(role)


# --- demonstration of permission enforcement --------------------------------


@router.get("/api/rbac/test-edit")
def test_edit_permission(
    current_user: User = Depends(require_permission("EDIT")),
) -> dict[str, str]:
    """
    A protected endpoint that exists purely to prove enforcement works.

    Any user without the EDIT permission gets 403 here, no matter what the
    React UI shows them. Try it as an Employee (VIEW only) and as an admin.
    """
    return {
        "message": "You have the EDIT permission.",
        "username": current_user.username,
    }


@router.get("/api/rbac/whoami")
def whoami(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    """A compact summary, handy when checking access from the command line."""
    return {
        "username": current_user.username,
        "roles": [role.code for role in rbac_service.get_user_roles(db, current_user)],
        "permissions": sorted(rbac_service.get_user_permission_codes(db, current_user)),
        "applications": [
            app.code for app in rbac_service.get_user_applications(db, current_user)
        ],
    }
