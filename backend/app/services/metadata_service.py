"""
Metadata lookups that respect the caller's access.

Every function here answers "give me this piece of metadata, but only if this
user is allowed to see it". Each one delegates the access question to
`rbac_service` rather than writing its own joins, so there is still exactly one
place where access is decided.

Returning None for "not allowed" and for "does not exist" is deliberate: the
endpoints turn both into the same response, so nobody can discover which
dashboards exist by trying codes and watching for a different error.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.application import Application
from app.models.dashboard import Dashboard
from app.models.dashboard_widget import DashboardWidget
from app.models.screen import Screen
from app.models.user import User
from app.services import rbac_service


def get_application_for_user(
    db: Session, user: User, application_code: str
) -> Application | None:
    """One application, if the user may open it."""
    for application in rbac_service.get_user_applications(db, user):
        if application.code == application_code:
            return application
    return None


def get_screen_for_user(db: Session, user: User, screen_code: str) -> Screen | None:
    """
    One screen, if the user may open it.

    `get_user_screens` already excludes screens whose application is not
    accessible, so this cannot leak a screen from an application the user
    cannot enter.
    """
    for screen in rbac_service.get_user_screens(db, user):
        if screen.code == screen_code:
            return screen
    return None


def get_dashboards_for_screen(db: Session, screen: Screen) -> list[Dashboard]:
    """The active dashboards on a screen, in display order."""
    return list(
        db.scalars(
            select(Dashboard)
            .where(Dashboard.screen_id == screen.id, Dashboard.is_active.is_(True))
            .order_by(Dashboard.display_order, Dashboard.name)
        )
    )


def get_dashboard_for_user(
    db: Session, user: User, dashboard_code: str
) -> Dashboard | None:
    """
    One dashboard, if the user may open the screen it belongs to.

    A dashboard has no access rules of its own - it inherits them from its
    screen, which inherits them from its application. That is the whole chain
    working in reverse.
    """
    dashboard = db.scalar(
        select(Dashboard)
        .options(selectinload(Dashboard.screen))
        .where(Dashboard.code == dashboard_code, Dashboard.is_active.is_(True))
    )
    if dashboard is None:
        return None

    if get_screen_for_user(db, user, dashboard.screen.code) is None:
        return None

    return dashboard


def get_widgets_for_dashboard(
    db: Session, dashboard: Dashboard
) -> list[DashboardWidget]:
    """The active widgets on a dashboard, in display order."""
    return list(
        db.scalars(
            select(DashboardWidget)
            .where(
                DashboardWidget.dashboard_id == dashboard.id,
                DashboardWidget.is_active.is_(True),
            )
            .order_by(DashboardWidget.display_order, DashboardWidget.id)
        )
    )
