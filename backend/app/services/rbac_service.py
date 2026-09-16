"""
RBAC service - the single place that answers "what may this user do?".

Every access question in the platform is answered here, so authorization logic
never gets copied into individual endpoints. If a rule changes, it changes once.

The chain the platform follows is:

    User -> Roles -> Permissions
                  -> Applications -> Screens

A user has roles; roles carry permissions, application access and screen
access. Nothing is hardcoded - all of it is rows in the database, which is what
makes the platform metadata-driven. There is deliberately no
`if role == "SUPER_ADMIN"` anywhere: a Super Admin sees everything only because
the seed gave that role every link.

Note that inactive rows are filtered out everywhere. Deactivating a role,
application or screen immediately removes it from everyone's access without
deleting any configuration.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.associations import (
    role_applications,
    role_permissions,
    role_screens,
    user_roles,
)
from app.models.permission import Permission
from app.models.role import Role
from app.models.screen import Screen
from app.models.user import User


def get_user_roles(db: Session, user: User) -> list[Role]:
    """Every active role assigned to the user."""
    return list(
        db.scalars(
            select(Role)
            .join(user_roles, user_roles.c.role_id == Role.id)
            .where(user_roles.c.user_id == user.id, Role.is_active.is_(True))
            .order_by(Role.code)
        )
    )


def get_user_permissions(db: Session, user: User) -> list[Permission]:
    """
    Every permission the user holds, through any of their roles.

    Two roles may both grant VIEW; .distinct() means it is listed once.
    """
    return list(
        db.scalars(
            select(Permission)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .join(Role, Role.id == role_permissions.c.role_id)
            .join(user_roles, user_roles.c.role_id == Role.id)
            .where(user_roles.c.user_id == user.id, Role.is_active.is_(True))
            .distinct()
            .order_by(Permission.code)
        )
    )


def get_user_permission_codes(db: Session, user: User) -> set[str]:
    """The user's permissions as a set of codes, e.g. {"VIEW", "EDIT"}."""
    return {permission.code for permission in get_user_permissions(db, user)}


def get_user_applications(db: Session, user: User) -> list[Application]:
    """
    Every application the user may open, in display order.

    This is what the frontend menu is built from. The three platform-admin
    applications appear here only for a user whose role is linked to them,
    which is why an ordinary business role can never see them.
    """
    return list(
        db.scalars(
            select(Application)
            .join(role_applications, role_applications.c.application_id == Application.id)
            .join(Role, Role.id == role_applications.c.role_id)
            .join(user_roles, user_roles.c.role_id == Role.id)
            .where(
                user_roles.c.user_id == user.id,
                Role.is_active.is_(True),
                Application.is_active.is_(True),
            )
            .distinct()
            .order_by(Application.display_order, Application.name)
        )
    )


def get_user_screens(
    db: Session, user: User, application_code: str | None = None
) -> list[Screen]:
    """
    Every screen the user may open, optionally limited to one application.

    Screen access is stored separately from application access, so a role can
    open an application without seeing all of its pages - an Employee can open
    Expense Management but not the Expense Approval screen.

    The join to Application is a safety net: a screen is never returned unless
    its application is also accessible and active, so revoking an application
    revokes its screens too.
    """
    accessible_application_ids = select(Application.id).join(
        role_applications, role_applications.c.application_id == Application.id
    ).join(Role, Role.id == role_applications.c.role_id).join(
        user_roles, user_roles.c.role_id == Role.id
    ).where(
        user_roles.c.user_id == user.id,
        Role.is_active.is_(True),
        Application.is_active.is_(True),
    )

    query = (
        select(Screen)
        .join(role_screens, role_screens.c.screen_id == Screen.id)
        .join(Role, Role.id == role_screens.c.role_id)
        .join(user_roles, user_roles.c.role_id == Role.id)
        .join(Application, Application.id == Screen.application_id)
        .where(
            user_roles.c.user_id == user.id,
            Role.is_active.is_(True),
            Screen.is_active.is_(True),
            Screen.application_id.in_(accessible_application_ids),
        )
        .distinct()
        .order_by(Screen.display_order, Screen.name)
    )

    if application_code is not None:
        query = query.where(Application.code == application_code)

    return list(db.scalars(query))


def count_active_applications(db: Session) -> int:
    """
    How many applications exist and are active, for anyone.

    Used only as the denominator in "5 of 8". It is not an access check.
    """
    return len(
        list(db.scalars(select(Application.id).where(Application.is_active.is_(True))))
    )


def has_permission(db: Session, user: User, permission_code: str) -> bool:
    """Does the user hold this permission through any role?"""
    return permission_code in get_user_permission_codes(db, user)


def can_access_application(db: Session, user: User, application_code: str) -> bool:
    """May the user open this application?"""
    return any(
        application.code == application_code
        for application in get_user_applications(db, user)
    )


def can_access_screen(db: Session, user: User, screen_code: str) -> bool:
    """May the user open this screen?"""
    return any(screen.code == screen_code for screen in get_user_screens(db, user))


# --- changing assignments ---------------------------------------------------


def assign_role_to_user(db: Session, user: User, role: Role) -> bool:
    """
    Give a user a role. Returns False if they already had it.

    Assigning the same role twice would violate the composite primary key on
    user_roles, so the membership check is what keeps this safe to repeat.
    """
    if role in user.roles:
        return False
    user.roles.append(role)
    db.commit()
    return True


def remove_role_from_user(db: Session, user: User, role: Role) -> bool:
    """Take a role away from a user. Returns False if they did not have it."""
    if role not in user.roles:
        return False
    user.roles.remove(role)
    db.commit()
    return True


def _toggle(collection: list, item, add: bool) -> bool:
    """
    Add or remove an item from a relationship list.

    Returns True if something actually changed. The membership check is what
    makes both operations safe to repeat: adding twice is not an error, and
    neither is removing something that was never there.
    """
    if add:
        if item in collection:
            return False
        collection.append(item)
    else:
        if item not in collection:
            return False
        collection.remove(item)
    return True


def set_role_permission(db: Session, role: Role, permission: Permission,
                        granted: bool) -> bool:
    """Grant or revoke one permission on a role."""
    changed = _toggle(role.permissions, permission, granted)
    db.commit()
    return changed


def set_role_application(db: Session, role: Role, application: Application,
                         granted: bool) -> bool:
    """Grant or revoke access to one application for a role."""
    changed = _toggle(role.applications, application, granted)
    db.commit()
    return changed


def set_role_screen(db: Session, role: Role, screen: Screen, granted: bool) -> bool:
    """Grant or revoke access to one screen for a role."""
    changed = _toggle(role.screens, screen, granted)
    db.commit()
    return changed
