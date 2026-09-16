"""
Access endpoints - what the signed-in user is allowed to see.

These are the endpoints the React app calls to build itself. They are
deliberately read-only and available to every authenticated user: each one
describes only that caller's own access, so there is nothing to hide.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.database import get_db
from app.models.user import User
from app.schemas.auth import UserResponse
from app.schemas.rbac import (
    AccessResponse,
    ApplicationResponse,
    DashboardWidgetResponse,
    DashboardWithWidgetsResponse,
    PermissionResponse,
    RoleResponse,
    ScreenResponse,
)
from app.services import dashboard_data_service, metadata_service, rbac_service


def _not_available(what: str) -> HTTPException:
    """
    One response for "no such thing" and for "not yours".

    Distinguishing them would let anyone map out the platform by trying codes
    and watching which error comes back.
    """
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No {what} available to you with that code.",
    )

router = APIRouter(prefix="/api/access", tags=["access"])


@router.get("/me", response_model=AccessResponse)
def read_my_access(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AccessResponse:
    """
    Everything the frontend needs to draw the application menu.

    One request returns identity, roles, permissions and accessible
    applications, so the React app never has to guess what a role means.
    """
    return AccessResponse(
        user=UserResponse.model_validate(current_user),
        roles=[RoleResponse.model_validate(r)
               for r in rbac_service.get_user_roles(db, current_user)],
        permissions=[PermissionResponse.model_validate(p)
                     for p in rbac_service.get_user_permissions(db, current_user)],
        applications=[ApplicationResponse.model_validate(a)
                      for a in rbac_service.get_user_applications(db, current_user)],
        total_applications=rbac_service.count_active_applications(db),
    )


@router.get(
    "/applications/{application_code}/screens",
    response_model=list[ScreenResponse],
)
def read_application_screens(
    application_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ScreenResponse]:
    """
    The screens this user may open inside one application.

    If the user cannot open the application at all, this is a 403 rather than
    an empty list - an empty list would wrongly suggest the application exists
    for them but happens to have no pages.
    """
    if not rbac_service.can_access_application(db, current_user, application_code):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"You do not have access to the {application_code} application.",
        )

    screens = rbac_service.get_user_screens(db, current_user, application_code)
    return [ScreenResponse.model_validate(screen) for screen in screens]


@router.get("/applications/{application_code}", response_model=ApplicationResponse)
def read_application(
    application_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplicationResponse:
    """Metadata for one application the caller may open."""
    application = metadata_service.get_application_for_user(
        db, current_user, application_code
    )
    if application is None:
        raise _not_available("application")
    return ApplicationResponse.model_validate(application)


@router.get("/screens/{screen_code}", response_model=ScreenResponse)
def read_screen(
    screen_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ScreenResponse:
    """Metadata for one screen the caller may open."""
    screen = metadata_service.get_screen_for_user(db, current_user, screen_code)
    if screen is None:
        raise _not_available("screen")
    return ScreenResponse.model_validate(screen)


@router.get(
    "/screens/{screen_code}/dashboards",
    response_model=list[DashboardWithWidgetsResponse],
)
def read_screen_dashboards(
    screen_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DashboardWithWidgetsResponse]:
    """
    The dashboards on a screen, each with its widgets.

    Widgets come back in the same response so a screen renders from one
    request instead of one per dashboard.
    """
    screen = metadata_service.get_screen_for_user(db, current_user, screen_code)
    if screen is None:
        raise _not_available("screen")

    return [
        DashboardWithWidgetsResponse(
            **DashboardWithWidgetsResponse.model_validate(dashboard).model_dump(
                exclude={"widgets"}
            ),
            widgets=[
                DashboardWidgetResponse.model_validate(w)
                for w in metadata_service.get_widgets_for_dashboard(db, dashboard)
            ],
        )
        for dashboard in metadata_service.get_dashboards_for_screen(db, screen)
    ]


@router.get(
    "/dashboards/{dashboard_code}/widgets",
    response_model=list[DashboardWidgetResponse],
)
def read_dashboard_widgets(
    dashboard_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DashboardWidgetResponse]:
    """
    The widgets of one dashboard.

    A dashboard has no access rules of its own: it is reachable exactly when
    its screen is.
    """
    dashboard = metadata_service.get_dashboard_for_user(db, current_user, dashboard_code)
    if dashboard is None:
        raise _not_available("dashboard")

    return [
        DashboardWidgetResponse.model_validate(w)
        for w in metadata_service.get_widgets_for_dashboard(db, dashboard)
    ]


@router.get("/dashboards/{dashboard_code}/data", response_model=dict[str, dict])
def read_dashboard_data(
    dashboard_code: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, dict]:
    """
    Live values for the widgets of a dashboard that declare a data source.

    Keyed by widget code. The frontend merges each entry over that widget's
    stored config, so titles, chart types and layout still come from metadata
    while the numbers come from the database - narrowed to this user's scope.

    Widgets with no data source are absent and keep their sample values.
    """
    dashboard = metadata_service.get_dashboard_for_user(db, current_user, dashboard_code)
    if dashboard is None:
        raise _not_available("dashboard")

    return dashboard_data_service.get_dashboard_data(db, current_user, dashboard)
