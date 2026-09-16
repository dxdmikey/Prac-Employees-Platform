"""
Pydantic schemas for RBAC.

Each one is an explicit list of the fields the API is willing to send. The
SQLAlchemy models carry more than this (password_hash, timestamps, internal
relationships) and none of it leaks unless it is named here.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import UserResponse


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None = None
    is_system_role: bool
    is_active: bool


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None = None


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None = None
    icon: str | None = None
    route: str | None = None
    is_platform_admin_app: bool
    display_order: int


class ScreenResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    code: str
    name: str
    description: str | None = None
    route: str | None = None
    display_order: int


class AccessResponse(BaseModel):
    """
    Everything the frontend needs after login, in one request.

    The React app builds its whole menu from this: who you are, and exactly
    which applications you may open. It never decides visibility itself.
    """

    user: UserResponse
    roles: list[RoleResponse]
    permissions: list[PermissionResponse]
    applications: list[ApplicationResponse]
    # How many active applications the platform has in total, so the UI can
    # show "5 of 8" without knowing that the number is 8. Change the seed and
    # the denominator changes with it.
    total_applications: int


class BusinessUnitRef(BaseModel):
    """A business unit reduced to what the admin table needs to show."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str


class UserWithRolesResponse(BaseModel):
    """
    A user with both halves of their authorisation - roles (what) and
    business units (where) - so the admin screen loads in one request.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    first_name: str
    last_name: str
    is_active: bool
    roles: list[RoleResponse] = []
    business_units: list[BusinessUnitRef] = []


class AssignRoleRequest(BaseModel):
    """Body of POST /api/users/{user_id}/roles."""

    role_id: int = Field(gt=0)


class AssignPermissionRequest(BaseModel):
    """Body of POST /api/roles/{role_id}/permissions."""

    permission_id: int = Field(gt=0)


class AssignApplicationRequest(BaseModel):
    """Body of POST /api/roles/{role_id}/applications."""

    application_id: int = Field(gt=0)


class AssignScreenRequest(BaseModel):
    """Body of POST /api/roles/{role_id}/screens."""

    screen_id: int = Field(gt=0)


class RoleScreenResponse(BaseModel):
    """A screen shown next to the application it belongs to."""

    id: int
    code: str
    name: str
    application_code: str
    application_name: str


class DashboardResponse(BaseModel):
    """A dashboard, without its widgets."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    screen_id: int
    code: str
    name: str
    description: str | None = None
    config_json: dict | None = None
    display_order: int


class DashboardWidgetResponse(BaseModel):
    """
    One tile. `widget_type` tells the frontend which component to render and
    `config_json` carries everything that component needs.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    dashboard_id: int
    code: str
    title: str
    widget_type: str
    config_json: dict | None = None
    grid_x: int
    grid_y: int
    width: int
    height: int
    display_order: int


class DashboardWithWidgetsResponse(DashboardResponse):
    """A dashboard and its widgets in one response, so a screen loads in one call."""

    widgets: list[DashboardWidgetResponse] = []
