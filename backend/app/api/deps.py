"""
Shared FastAPI dependencies.

A "dependency" is a function FastAPI runs before your endpoint. Whatever it
returns is handed to the endpoint as an argument. get_current_user() below is
what turns an Authorization header into a User object, so any protected
endpoint can simply ask for a User and trust it is there.
"""

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.user import User
from app.services import auth_service, rbac_service

# HTTPBearer reads the "Authorization: Bearer <token>" header. auto_error=False
# means a missing header returns None instead of raising, so we can send one
# consistent 401 for "no token" and "bad token" alike.
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Identify the caller, or reject the request with 401.

    Add it to any endpoint that needs a signed-in user:

        def endpoint(current_user: User = Depends(get_current_user)): ...
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        # Part of the HTTP spec for 401 responses: it tells the client what
        # kind of credentials the endpoint expects.
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise unauthorized

    user = auth_service.get_user_for_token(db, credentials.credentials)
    if user is None:
        raise unauthorized

    return user


# ---------------------------------------------------------------------------
# Authorization
#
# get_current_user above answers "who are you?" (authentication).
# The two builders below answer "may you do this?" (authorization).
#
# They are *factories*: calling one returns a dependency function configured
# for a particular permission or application. That is what lets an endpoint
# say what it needs in one readable line:
#
#     @router.get("/thing", dependencies=[Depends(require_permission("EDIT"))])
#
# Checking on the server is not optional. Hiding a button in React only hides
# the button - anyone can still call the API directly with curl.
# ---------------------------------------------------------------------------


def require_permission(permission_code: str) -> Callable[..., User]:
    """
    Build a dependency that allows the request only if the signed-in user holds
    the given permission (e.g. "EDIT").

    403 Forbidden is the right status here, not 401: we know who the user is,
    they are simply not allowed.
    """

    def dependency(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not rbac_service.has_permission(db, current_user, permission_code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the {permission_code} permission.",
            )
        return current_user

    return dependency


def require_application(application_code: str) -> Callable[..., User]:
    """
    Build a dependency that allows the request only if the signed-in user may
    open the given application (e.g. "USER_ROLE_MANAGEMENT").

    This is how the RBAC management endpoints are protected. It is fully
    metadata-driven: nothing checks for a role named SUPER_ADMIN, it simply
    asks whether this user's roles link to that application. A role with the
    CONFIGURE permission but no platform-admin application still cannot
    administer the platform.
    """

    def dependency(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not rbac_service.can_access_application(db, current_user, application_code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You do not have access to the {application_code} application.",
            )
        return current_user

    return dependency
