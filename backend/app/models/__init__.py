"""
SQLAlchemy models.

Importing every model here serves two purposes:

1. Alembic imports this package once and therefore sees all tables on
   Base.metadata, so autogenerate does not miss any.
2. SQLAlchemy can resolve the string names used in relationships (such as
   "Role" or "BusinessUnit") only after those classes have been imported.

Add every new model to this file.
"""

from app.models.application import Application
from app.models.auth_token import AuthToken
from app.models.associations import (
    role_applications,
    role_permissions,
    role_screens,
    user_business_units,
    user_roles,
    workflow_transition_roles,
)
from app.models.business_unit import BusinessUnit
from app.models.business_unit_type import BusinessUnitType
from app.models.dashboard import Dashboard
from app.models.dashboard_widget import DashboardWidget
from app.models.employee import Employee
from app.models.leave_request import LeaveRequest
from app.models.leave_type import LeaveType
from app.models.permission import Permission
from app.models.role import Role
from app.models.screen import Screen
from app.models.user import User
from app.models.workflow import Workflow
from app.models.workflow_demo_request import WorkflowDemoRequest
from app.models.workflow_history import WorkflowHistory
from app.models.workflow_state import WorkflowState
from app.models.workflow_transition import WorkflowTransition

__all__ = [
    "Application",
    "AuthToken",
    "BusinessUnit",
    "BusinessUnitType",
    "Dashboard",
    "DashboardWidget",
    "Employee",
    "LeaveRequest",
    "LeaveType",
    "Permission",
    "Role",
    "Screen",
    "User",
    "Workflow",
    "WorkflowDemoRequest",
    "WorkflowHistory",
    "WorkflowState",
    "WorkflowTransition",
    "role_applications",
    "role_permissions",
    "role_screens",
    "user_business_units",
    "workflow_transition_roles",
    "user_roles",
]
