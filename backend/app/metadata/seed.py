"""
Development metadata seed.

The platform is metadata-driven, which means an empty database is a platform
with no roles, no applications and no screens - there is nothing to show. This
module inserts a small, realistic starting set so RBAC can be demonstrated.

Three important properties:

1. **Idempotent.** Everything is matched by its `code`, so running the seed
   twice changes nothing the second time.
2. **Authoritative.** Role access is *reconciled*, not merely topped up: links
   listed below are created, and links that are not listed are removed. That is
   what lets a correction to this file actually take effect. The trade-off:
   re-running the seed discards role changes made through the admin UI.
3. **Importable.** The API tests call `seed_all()` too, so the tests exercise
   exactly the same metadata you see in the browser.

No passwords appear anywhere in this file. The admin user is created
separately by `scripts/create_admin_user.py`; this seed only grants it the
SUPER_ADMIN role if it already exists.
"""

from dataclasses import dataclass
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.attendance import Attendance
from app.models.business_unit import BusinessUnit
from app.models.business_unit_type import BusinessUnitType
from app.models.dashboard import Dashboard
from app.models.dashboard_widget import DashboardWidget
from app.models.employee import Employee
from app.models.expense import Expense
from app.models.expense_category import ExpenseCategory
from app.models.leave_request import LeaveRequest
from app.models.leave_type import LeaveType
from app.models.permission import Permission
from app.models.role import Role
from app.models.screen import Screen
from app.models.timesheet import Timesheet
from app.models.user import User
from app.models.workflow import Workflow
from app.models.workflow_history import WorkflowHistory
from app.models.workflow_state import WorkflowState
from app.models.workflow_transition import WorkflowTransition
from app.services import attendance_service, leave_service

# A marker meaning "every one of them", used in the mappings further down.
ALL = "*"

ADMIN_USERNAME = "admin"


# ---------------------------------------------------------------------------
# 1. What exists
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleSeed:
    code: str
    name: str
    description: str


@dataclass(frozen=True)
class PermissionSeed:
    code: str
    name: str
    description: str


@dataclass(frozen=True)
class ApplicationSeed:
    code: str
    name: str
    description: str
    icon: str
    is_platform_admin_app: bool
    display_order: int


@dataclass(frozen=True)
class ScreenSeed:
    application_code: str
    code: str
    name: str
    display_order: int


ROLES: list[RoleSeed] = [
    RoleSeed("SUPER_ADMIN", "Super Admin", "Full platform-wide administration."),
    RoleSeed(
        "APPLICATION_ADMIN",
        "Application Admin",
        "Administers the specific applications assigned to them. Grants no "
        "application access on its own - an administrator assigns the "
        "applications this role may configure.",
    ),
    RoleSeed("HR", "HR", "Human resources staff."),
    RoleSeed("MANAGER", "Manager", "Manages a team and approves their requests."),
    RoleSeed("EMPLOYEE", "Employee", "Standard employee self-service access."),
]

PERMISSIONS: list[PermissionSeed] = [
    PermissionSeed("VIEW", "View", "Read data."),
    PermissionSeed("CREATE", "Create", "Add new records."),
    PermissionSeed("EDIT", "Edit", "Change existing records."),
    PermissionSeed("DELETE", "Delete", "Remove records."),
    PermissionSeed("APPROVE", "Approve", "Approve or reject submitted items."),
    PermissionSeed("EXPORT", "Export", "Download data."),
    PermissionSeed("CONFIGURE", "Configure", "Change configuration and metadata."),
]

# The eight applications. The last three are platform administration.
#
# LMS in this project means **Leave Management System**, not Learning
# Management. The code is LEAVE_MANAGEMENT so the name cannot be misread again.
APPLICATIONS: list[ApplicationSeed] = [
    ApplicationSeed("EMPLOYEE_MANAGEMENT", "Employee Management",
                    "Employee records and profiles.", "people", False, 1),
    ApplicationSeed("LEAVE_MANAGEMENT", "Leave Management System",
                    "Leave balances, requests and approvals.", "calendar", False, 2),
    ApplicationSeed("PAYROLL", "Payroll",
                    "Salary information and payroll processing.", "payments", False, 3),
    ApplicationSeed("ATTENDANCE_TIMESHEET", "Attendance & Timesheet",
                    "Attendance tracking and timesheets.", "schedule", False, 4),
    ApplicationSeed("EXPENSE_MANAGEMENT", "Expense Management",
                    "Expense claims and approvals.", "receipt", False, 5),
    ApplicationSeed("USER_MANAGEMENT", "User Management",
                    "Platform users.", "person", True, 6),
    ApplicationSeed("ROLE_MANAGEMENT", "Role Management",
                    "Roles and permissions.", "badge", True, 7),
    ApplicationSeed("USER_ROLE_MANAGEMENT", "User-Role Management",
                    "Assign roles to users.", "link", True, 8),
]

# An application whose code changed. The seed renames the existing row instead
# of creating a second one, so every existing link is preserved.
RENAMED_APPLICATIONS: dict[str, str] = {"LMS": "LEAVE_MANAGEMENT"}

SCREENS: list[ScreenSeed] = [
    ScreenSeed("EMPLOYEE_MANAGEMENT", "EMPLOYEE_DASHBOARD", "Employee Dashboard", 1),
    ScreenSeed("EMPLOYEE_MANAGEMENT", "EMPLOYEE_LIST", "Employee List", 2),
    ScreenSeed("EMPLOYEE_MANAGEMENT", "EMPLOYEE_PROFILE", "Employee Profile", 3),

    ScreenSeed("LEAVE_MANAGEMENT", "LEAVE_DASHBOARD", "Leave Dashboard", 1),
    ScreenSeed("LEAVE_MANAGEMENT", "MY_LEAVE", "My Leave", 2),
    ScreenSeed("LEAVE_MANAGEMENT", "LEAVE_REQUESTS", "Leave Requests", 3),
    ScreenSeed("LEAVE_MANAGEMENT", "LEAVE_APPROVAL", "Leave Approval", 4),

    ScreenSeed("PAYROLL", "PAYROLL_DASHBOARD", "Payroll Dashboard", 1),
    ScreenSeed("PAYROLL", "MY_SALARY", "My Salary", 2),
    ScreenSeed("PAYROLL", "SALARY_COMPONENTS", "Salary Components", 3),

    ScreenSeed("ATTENDANCE_TIMESHEET", "ATTENDANCE_DASHBOARD", "Attendance Dashboard", 1),
    ScreenSeed("ATTENDANCE_TIMESHEET", "MY_ATTENDANCE", "My Attendance", 2),
    ScreenSeed("ATTENDANCE_TIMESHEET", "TIMESHEET", "Timesheet", 3),
    # Stage 10 adds the two management screens. Employees are excluded from
    # both below, exactly as they are from Leave Approval.
    ScreenSeed("ATTENDANCE_TIMESHEET", "TEAM_ATTENDANCE", "Team Attendance", 4),
    ScreenSeed("ATTENDANCE_TIMESHEET", "TIMESHEET_APPROVAL", "Timesheet Approval", 5),

    ScreenSeed("EXPENSE_MANAGEMENT", "EXPENSE_DASHBOARD", "Expense Dashboard", 1),
    ScreenSeed("EXPENSE_MANAGEMENT", "MY_EXPENSES", "My Expenses", 2),
    ScreenSeed("EXPENSE_MANAGEMENT", "EXPENSE_APPROVAL", "Expense Approval", 3),

    ScreenSeed("USER_MANAGEMENT", "USER_LIST", "User List", 1),
    ScreenSeed("ROLE_MANAGEMENT", "ROLE_LIST", "Role List", 1),
    ScreenSeed("USER_ROLE_MANAGEMENT", "USER_ROLE_ASSIGNMENT", "User Role Assignment", 1),
]

# A screen whose code changed. As with applications, the row is renamed rather
# than deleted and recreated, so its role_screens links survive.
RENAMED_SCREENS: dict[str, str] = {"EXPENSE_LIST": "MY_EXPENSES"}


@dataclass(frozen=True)
class DashboardSeed:
    screen_code: str
    code: str
    name: str
    description: str
    display_order: int


@dataclass(frozen=True)
class WidgetSeed:
    dashboard_code: str
    code: str
    title: str
    widget_type: str        # stat | bar | line | pie | table
    config: dict
    width: int              # columns out of 12
    display_order: int


# Dashboards hang off the *_DASHBOARD screens. A screen may hold more than one.
DASHBOARDS: list[DashboardSeed] = [
    DashboardSeed("PAYROLL_DASHBOARD", "PAYROLL_SUMMARY", "Summary",
                  "Headline payroll figures for the current month.", 1),
    DashboardSeed("PAYROLL_DASHBOARD", "SALARY_BREAKDOWN", "Salary Breakdown",
                  "How the payroll splits across components.", 2),
    DashboardSeed("LEAVE_DASHBOARD", "LEAVE_OVERVIEW", "Leave Overview",
                  "Leave taken and pending across the team.", 1),
    DashboardSeed("ATTENDANCE_DASHBOARD", "ATTENDANCE_OVERVIEW", "Attendance Overview",
                  "Attendance trend and today's status.", 1),
    # A screen may hold more than one dashboard - Payroll already does. Keeping
    # timesheets on their own dashboard rather than mixing them into the
    # attendance tiles keeps the two questions visually separate, which is the
    # same reason they are separate tables.
    DashboardSeed("ATTENDANCE_DASHBOARD", "TIMESHEET_SUMMARY", "Timesheet Summary",
                  "Recorded work, and where it has got to.", 2),
    DashboardSeed("EXPENSE_DASHBOARD", "EXPENSE_OVERVIEW", "Expense Overview",
                  "Expense claims by status and category.", 1),
    DashboardSeed("EMPLOYEE_DASHBOARD", "HEADCOUNT_OVERVIEW", "Headcount Overview",
                  "Headcount and joiners.", 1),
]

# The widgets on those dashboards.
#
# Every number below is sample data living in metadata, which is the whole
# point at this stage: the rendering path from database to chart is real even
# though the analytics behind it are not. Stage 12 replaces `config` values
# with the output of real queries; no React code has to change when it does.
WIDGETS: list[WidgetSeed] = [
    # --- Payroll: Summary --------------------------------------------------
    WidgetSeed("PAYROLL_SUMMARY", "TOTAL_PAYROLL", "Total payroll", "stat",
               {"value": 486200, "unit": "currency", "caption": "This month"}, 3, 1),
    WidgetSeed("PAYROLL_SUMMARY", "HEADCOUNT_PAID", "Employees paid", "stat",
               {"value": 128, "caption": "Across all branches"}, 3, 2),
    WidgetSeed("PAYROLL_SUMMARY", "AVERAGE_SALARY", "Average salary", "stat",
               {"value": 3798, "unit": "currency", "caption": "Gross, monthly"}, 3, 3),
    WidgetSeed("PAYROLL_SUMMARY", "PAYROLL_TREND", "Payroll by month", "line",
               {"categories": ["Apr", "May", "Jun", "Jul", "Aug", "Sep"],
                "series": [{"name": "Gross payroll",
                            "data": [455000, 461000, 468500, 470200, 479000, 486200]}]},
               12, 4),

    # --- Payroll: Salary Breakdown ----------------------------------------
    WidgetSeed("SALARY_BREAKDOWN", "COMPONENT_SPLIT", "Salary components", "pie",
               {"series": [{"name": "Basic", "value": 292000},
                           {"name": "Allowances", "value": 118000},
                           {"name": "Bonus", "value": 41000},
                           {"name": "Deductions", "value": 35200}]}, 6, 1),
    WidgetSeed("SALARY_BREAKDOWN", "COMPONENT_TABLE", "Component detail", "table",
               {"columns": ["Component", "Amount", "Share"],
                "rows": [["Basic", "292,000", "60%"],
                         ["Allowances", "118,000", "24%"],
                         ["Bonus", "41,000", "9%"],
                         ["Deductions", "35,200", "7%"]]}, 6, 2),

    # --- Leave -------------------------------------------------------------
    #
    # Backed by real data, like the employee tiles below. Every one of these
    # resolves against the caller's own visible requests, so the same seven
    # widget rows show an employee their own leave and a manager their
    # branch's - one dashboard definition, not two.
    WidgetSeed("LEAVE_OVERVIEW", "TOTAL_REQUESTS", "Total requests", "stat",
               {"data_source": "leave.total"}, 3, 1),
    WidgetSeed("LEAVE_OVERVIEW", "PENDING_REQUESTS", "Pending", "stat",
               {"data_source": "leave.pending"}, 3, 2),
    WidgetSeed("LEAVE_OVERVIEW", "APPROVED_REQUESTS", "Approved", "stat",
               {"data_source": "leave.approved"}, 3, 3),
    WidgetSeed("LEAVE_OVERVIEW", "REJECTED_REQUESTS", "Rejected", "stat",
               {"data_source": "leave.rejected"}, 3, 4),
    WidgetSeed("LEAVE_OVERVIEW", "TOTAL_DAYS", "Total days requested", "stat",
               {"data_source": "leave.total_days"}, 4, 5),
    WidgetSeed("LEAVE_OVERVIEW", "LEAVE_BY_TYPE", "Requests by leave type", "bar",
               {"data_source": "leave.by_type"}, 8, 6),
    WidgetSeed("LEAVE_OVERVIEW", "LEAVE_BY_STATUS", "Requests by status", "pie",
               {"data_source": "leave.by_status"}, 6, 7),
    WidgetSeed("LEAVE_OVERVIEW", "LEAVE_BY_MONTH", "Requests by month", "line",
               {"data_source": "leave.by_month"}, 6, 8),

    # --- Attendance --------------------------------------------------------
    #
    # Backed by real data. Every one of these resolves against the caller's own
    # visible attendance, so the same eight widget rows show an employee their
    # own record and a manager their team's - one dashboard definition, not two.
    WidgetSeed("ATTENDANCE_OVERVIEW", "PRESENT_TODAY", "Present today", "stat",
               {"data_source": "attendance.present_today"}, 3, 1),
    WidgetSeed("ATTENDANCE_OVERVIEW", "INCOMPLETE_TODAY", "Missing checkout", "stat",
               {"data_source": "attendance.incomplete_today"}, 3, 2),
    WidgetSeed("ATTENDANCE_OVERVIEW", "ON_LEAVE_TODAY", "On leave today", "stat",
               {"data_source": "attendance.on_leave_today"}, 3, 3),
    WidgetSeed("ATTENDANCE_OVERVIEW", "AVERAGE_HOURS", "Average day", "stat",
               {"data_source": "attendance.average_hours"}, 3, 4),
    WidgetSeed("ATTENDANCE_OVERVIEW", "TOTAL_HOURS", "Total hours worked", "stat",
               {"data_source": "attendance.total_hours"}, 4, 5),
    WidgetSeed("ATTENDANCE_OVERVIEW", "ATTENDANCE_TREND", "Attendance, last 14 days",
               "line", {"data_source": "attendance.by_day"}, 8, 6),
    WidgetSeed("ATTENDANCE_OVERVIEW", "ATTENDANCE_BY_STATUS", "Days by status", "pie",
               {"data_source": "attendance.by_status"}, 6, 7),
    WidgetSeed("ATTENDANCE_OVERVIEW", "HOURS_BY_EMPLOYEE", "Hours by employee", "bar",
               {"data_source": "attendance.hours_by_employee"}, 6, 8),

    # --- Timesheet ---------------------------------------------------------
    WidgetSeed("TIMESHEET_SUMMARY", "TIMESHEET_TOTAL", "Entries recorded", "stat",
               {"data_source": "timesheets.total"}, 3, 1),
    WidgetSeed("TIMESHEET_SUMMARY", "TIMESHEET_PENDING", "Awaiting review", "stat",
               {"data_source": "timesheets.submitted"}, 3, 2),
    WidgetSeed("TIMESHEET_SUMMARY", "TIMESHEET_APPROVED", "Approved", "stat",
               {"data_source": "timesheets.approved"}, 3, 3),
    WidgetSeed("TIMESHEET_SUMMARY", "TIMESHEET_APPROVED_HOURS", "Approved hours",
               "stat", {"data_source": "timesheets.approved_hours"}, 3, 4),
    WidgetSeed("TIMESHEET_SUMMARY", "TIMESHEET_BY_STATUS", "Entries by status", "pie",
               {"data_source": "timesheets.by_status"}, 6, 5),
    WidgetSeed("TIMESHEET_SUMMARY", "TIMESHEET_HOURS_BY_WEEK", "Hours logged by week",
               "line", {"data_source": "timesheets.hours_by_week"}, 6, 6),
    WidgetSeed("TIMESHEET_SUMMARY", "TIMESHEET_HOURS_BY_EMPLOYEE",
               "Hours logged by employee", "bar",
               {"data_source": "timesheets.hours_by_employee"}, 12, 7),

    # --- Expense -----------------------------------------------------------
    #
    # Backed by real data, and scoped: the same seven widget rows show an
    # employee their own claims and a manager their team's. `unit: currency`
    # is still metadata - the resolver supplies the number, the widget knows
    # how to render it as money.
    WidgetSeed("EXPENSE_OVERVIEW", "CLAIMS_TOTAL", "Claims", "stat",
               {"data_source": "expenses.total"}, 3, 1),
    WidgetSeed("EXPENSE_OVERVIEW", "CLAIMS_PENDING", "Awaiting approval", "stat",
               {"data_source": "expenses.submitted"}, 3, 2),
    WidgetSeed("EXPENSE_OVERVIEW", "CLAIMS_APPROVED", "Approved", "stat",
               {"data_source": "expenses.approved"}, 3, 3),
    WidgetSeed("EXPENSE_OVERVIEW", "CLAIMS_REJECTED", "Rejected", "stat",
               {"data_source": "expenses.rejected"}, 3, 4),
    WidgetSeed("EXPENSE_OVERVIEW", "CLAIM_VALUE", "Approved value", "stat",
               {"unit": "currency", "data_source": "expenses.approved_amount"}, 4, 5),
    WidgetSeed("EXPENSE_OVERVIEW", "BY_CATEGORY", "Spend by category", "bar",
               {"data_source": "expenses.by_category"}, 8, 6),
    WidgetSeed("EXPENSE_OVERVIEW", "BY_STATUS", "Claims by status", "pie",
               {"data_source": "expenses.by_status"}, 6, 7),
    WidgetSeed("EXPENSE_OVERVIEW", "BY_MONTH", "Spend by month", "line",
               {"data_source": "expenses.by_month"}, 6, 8),

    # --- Employee ----------------------------------------------------------
    #
    # These are the first widgets backed by real data. Instead of sample
    # numbers, each carries a `data_source` that the backend resolves against
    # PostgreSQL at request time - narrowed to the caller's business-unit
    # scope, so two people see different totals. Everything else about them
    # (title, chart type, width, order) is still plain metadata.
    WidgetSeed("HEADCOUNT_OVERVIEW", "TOTAL_EMPLOYEES", "Total employees", "stat",
               {"data_source": "employees.total"}, 3, 1),
    WidgetSeed("HEADCOUNT_OVERVIEW", "ACTIVE_EMPLOYEES", "Active", "stat",
               {"data_source": "employees.active"}, 3, 2),
    WidgetSeed("HEADCOUNT_OVERVIEW", "INACTIVE_EMPLOYEES", "Inactive", "stat",
               {"data_source": "employees.inactive"}, 3, 3),
    WidgetSeed("HEADCOUNT_OVERVIEW", "BUSINESS_UNITS", "Business units", "stat",
               {"data_source": "employees.business_units"}, 3, 4),
    WidgetSeed("HEADCOUNT_OVERVIEW", "BY_BUSINESS_UNIT", "Employees by business unit",
               "bar", {"data_source": "employees.by_business_unit"}, 8, 5),
    WidgetSeed("HEADCOUNT_OVERVIEW", "BY_STATUS", "Employees by status", "pie",
               {"data_source": "employees.by_status"}, 4, 6),
]


@dataclass(frozen=True)
class EmployeeSeed:
    code: str
    first_name: str
    last_name: str
    job_title: str
    business_unit_code: str
    manager_code: str | None
    status: str = "ACTIVE"
    # Links this HR record to an existing development login, where one exists.
    # Most employees have no account at all, which is the normal case.
    username: str | None = None


# A small fictional workforce spread across the seeded organisation, ordered
# managers-first so a report always finds its manager already created.
#
# The spread is deliberate: it lets every level of business-unit scope be
# tested - Headquarters sees all 22, Company 1 sees 16, Branch 1 sees 8,
# Department 1 sees 4.
EMPLOYEES: list[EmployeeSeed] = [
    EmployeeSeed("EMP-001", "Ada", "Whitfield", "Chief Executive", "HQ", None),

    # --- Company 1 ---------------------------------------------------------
    EmployeeSeed("EMP-002", "Marcus", "Delgado", "Managing Director",
                 "COMPANY_1", "EMP-001"),
    EmployeeSeed("EMP-003", "Priya", "Raman", "HR Business Partner",
                 "COMPANY_1", "EMP-002", username="priya"),

    EmployeeSeed("EMP-004", "Raj", "Patel", "Branch Manager",
                 "BRANCH_1", "EMP-002", username="raj"),
    EmployeeSeed("EMP-005", "Jane", "Okafor", "Software Engineer",
                 "DEPARTMENT_1", "EMP-004", username="jane"),
    EmployeeSeed("EMP-006", "Tomas", "Lindqvist", "Software Engineer",
                 "DEPARTMENT_1", "EMP-004"),
    EmployeeSeed("EMP-007", "Grace", "Mbeki", "QA Analyst",
                 "DEPARTMENT_1", "EMP-004", status="ON_LEAVE"),
    EmployeeSeed("EMP-008", "Henrik", "Sorensen", "Support Engineer",
                 "DEPARTMENT_2", "EMP-004"),
    EmployeeSeed("EMP-009", "Leila", "Haddad", "Support Engineer",
                 "DEPARTMENT_2", "EMP-004"),
    EmployeeSeed("EMP-010", "Owen", "Brennan", "Support Lead",
                 "DEPARTMENT_2", "EMP-004", status="INACTIVE"),

    EmployeeSeed("EMP-011", "Sofia", "Marchetti", "Branch Manager",
                 "BRANCH_2", "EMP-002"),
    EmployeeSeed("EMP-012", "Daniel", "Okonkwo", "Accountant",
                 "DEPARTMENT_3", "EMP-011"),
    EmployeeSeed("EMP-013", "Yuki", "Tanaka", "Accountant",
                 "DEPARTMENT_3", "EMP-011"),
    EmployeeSeed("EMP-014", "Nadia", "Rahman", "Payroll Officer",
                 "DEPARTMENT_3", "EMP-011"),
    EmployeeSeed("EMP-015", "Peter", "Novak", "Facilities Coordinator",
                 "DEPARTMENT_4", "EMP-011"),
    EmployeeSeed("EMP-016", "Amara", "Diallo", "Facilities Assistant",
                 "DEPARTMENT_4", "EMP-011", status="ON_LEAVE"),

    # --- Company 2 ---------------------------------------------------------
    EmployeeSeed("EMP-017", "Elena", "Petrova", "Managing Director",
                 "COMPANY_2", "EMP-001"),
    EmployeeSeed("EMP-018", "Carlos", "Mendes", "Branch Manager",
                 "BRANCH_3", "EMP-017"),
    EmployeeSeed("EMP-019", "Fatima", "Zahra", "Sales Executive",
                 "DEPARTMENT_5", "EMP-018"),
    EmployeeSeed("EMP-020", "Jonas", "Weber", "Sales Executive",
                 "DEPARTMENT_5", "EMP-018", status="INACTIVE"),
    EmployeeSeed("EMP-021", "Mei", "Chen", "Logistics Planner",
                 "DEPARTMENT_6", "EMP-018"),
    EmployeeSeed("EMP-022", "Samuel", "Adeyemi", "Logistics Assistant",
                 "DEPARTMENT_6", "EMP-018"),
]


# ---------------------------------------------------------------------------
# Leave Management (Stage 9)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeaveTypeSeed:
    code: str
    name: str
    description: str
    # Informational only at this stage. Nothing enforces a balance yet - a
    # balance engine is deliberately out of scope, and when it arrives it
    # reads this column rather than replacing it.
    max_days: int | None


@dataclass(frozen=True)
class LeaveRequestSeed:
    employee_code: str
    leave_type_code: str
    # ISO strings, parsed once when the seed runs. Written as text so this
    # list reads like a spreadsheet rather than a wall of date(...) calls.
    start_date: str
    end_date: str
    # Where this fixture currently sits in LEAVE_APPROVAL. total_days is NOT
    # a field here: the seed calculates it with the same function the API
    # uses, so seeded data can never disagree with created data.
    state_code: str
    reason: str


# The kinds of leave, as rows. Adding "Compassionate Leave" is one more line
# here and an INSERT in the database - no enum, no migration, no code change.
LEAVE_TYPES: list[LeaveTypeSeed] = [
    LeaveTypeSeed("ANNUAL", "Annual Leave",
                  "Paid holiday from the yearly entitlement.", 25),
    LeaveTypeSeed("SICK", "Sick Leave",
                  "Paid absence through illness or injury.", 12),
    LeaveTypeSeed("CASUAL", "Casual Leave",
                  "Short personal absence, usually a day or two.", 6),
    LeaveTypeSeed("UNPAID", "Unpaid Leave",
                  "Approved absence with no pay for the period.", None),
]

# A small fictional set of requests spread across the organisation.
#
# It is shaped to make every access rule visible without reading any code:
#
#     Headquarters  25 requests   (admin sees all of them)
#     Company 1     21            (priya, HR)
#     Branch 1      13            (raj, Manager - his branch and its two
#                                  departments, never Branch 2 or Company 2)
#     Department 1   7            (of which 3 are jane's own)
#
# jane holds the EMPLOYEE role, which carries VIEW but not APPROVE, so she
# sees only her own three - the other four in her department are invisible to
# her. That difference between 7 and 3 is the point of the dataset.
#
# The states are spread too: 4 Draft, 8 Pending Approval, 10 Approved,
# 2 Rejected and 1 Cancelled, with start dates across six months so the
# monthly chart has a shape.
LEAVE_REQUESTS: list[LeaveRequestSeed] = [
    # --- Company 1 / Branch 1 / Department 1 ------------------------------
    LeaveRequestSeed("EMP-005", "ANNUAL", "2026-09-21", "2026-09-25",
                     "DRAFT", "Family holiday."),
    LeaveRequestSeed("EMP-005", "SICK", "2026-07-06", "2026-07-07",
                     "APPROVED", "Influenza, signed off by the GP."),
    LeaveRequestSeed("EMP-005", "CASUAL", "2026-08-17", "2026-08-17",
                     "REJECTED", "Personal errand."),
    LeaveRequestSeed("EMP-006", "ANNUAL", "2026-09-28", "2026-10-02",
                     "PENDING_APPROVAL", "Autumn break with family."),
    LeaveRequestSeed("EMP-006", "SICK", "2026-06-15", "2026-06-16",
                     "APPROVED", "Migraine."),
    LeaveRequestSeed("EMP-007", "ANNUAL", "2026-09-07", "2026-09-18",
                     "APPROVED", "Two weeks abroad."),
    LeaveRequestSeed("EMP-007", "CASUAL", "2026-10-12", "2026-10-13",
                     "PENDING_APPROVAL", "Moving house."),

    # --- Company 1 / Branch 1 / Department 2 ------------------------------
    LeaveRequestSeed("EMP-008", "ANNUAL", "2026-10-05", "2026-10-09",
                     "PENDING_APPROVAL", "Annual holiday."),
    LeaveRequestSeed("EMP-008", "UNPAID", "2026-11-02", "2026-11-06",
                     "DRAFT", "Unpaid week for a family commitment."),
    LeaveRequestSeed("EMP-009", "SICK", "2026-08-24", "2026-08-26",
                     "APPROVED", "Chest infection."),
    LeaveRequestSeed("EMP-009", "ANNUAL", "2026-09-14", "2026-09-16",
                     "PENDING_APPROVAL", "Long weekend."),
    LeaveRequestSeed("EMP-010", "CASUAL", "2026-07-20", "2026-07-20",
                     "CANCELLED", "No longer needed."),

    # --- Company 1 / Branch 1 (the manager's own request) -----------------
    # Raj can approve his team's leave but not this one: the engine offers an
    # owner only the actions that leave the initial state.
    LeaveRequestSeed("EMP-004", "ANNUAL", "2026-10-19", "2026-10-23",
                     "PENDING_APPROVAL", "Half-term week."),

    # --- Company 1 (head office) ------------------------------------------
    LeaveRequestSeed("EMP-003", "ANNUAL", "2026-09-01", "2026-09-04",
                     "APPROVED", "City break."),
    LeaveRequestSeed("EMP-003", "CASUAL", "2026-11-09", "2026-11-09",
                     "DRAFT", "Medical appointment."),
    LeaveRequestSeed("EMP-002", "ANNUAL", "2026-08-10", "2026-08-21",
                     "APPROVED", "Summer holiday."),

    # --- Company 1 / Branch 2 / Departments 3 and 4 -----------------------
    LeaveRequestSeed("EMP-012", "ANNUAL", "2026-09-21", "2026-09-23",
                     "PENDING_APPROVAL", "Attending a wedding."),
    LeaveRequestSeed("EMP-013", "SICK", "2026-07-13", "2026-07-14",
                     "APPROVED", "Food poisoning."),
    LeaveRequestSeed("EMP-014", "UNPAID", "2026-10-26", "2026-10-30",
                     "REJECTED", "Unpaid study leave."),
    LeaveRequestSeed("EMP-015", "ANNUAL", "2026-06-22", "2026-06-26",
                     "APPROVED", "Early summer break."),
    LeaveRequestSeed("EMP-016", "ANNUAL", "2026-09-07", "2026-09-18",
                     "APPROVED", "Extended trip home."),

    # --- Company 2 --------------------------------------------------------
    # None of these may ever appear for raj or priya. They are the control
    # group for the business-unit scope tests.
    LeaveRequestSeed("EMP-019", "ANNUAL", "2026-09-28", "2026-10-02",
                     "PENDING_APPROVAL", "Holiday."),
    LeaveRequestSeed("EMP-021", "SICK", "2026-08-03", "2026-08-04",
                     "APPROVED", "Dental surgery."),
    LeaveRequestSeed("EMP-022", "CASUAL", "2026-11-16", "2026-11-17",
                     "DRAFT", "Family matter."),
    LeaveRequestSeed("EMP-018", "ANNUAL", "2026-10-12", "2026-10-16",
                     "PENDING_APPROVAL", "Autumn leave."),
]

# ---------------------------------------------------------------------------
# Attendance & Timesheet (Stage 10)
# ---------------------------------------------------------------------------

# How far back the generated fixtures reach. Three weeks gives the trend chart
# a shape without burying the tables in history.
ATTENDANCE_HISTORY_DAYS = 21
TIMESHEET_HISTORY_DAYS = 21

# Employees who should have no recent attendance: they have left, so a row for
# last Tuesday would be wrong.
INACTIVE_EMPLOYEE_CODES = {
    seed.code for seed in EMPLOYEES if seed.status == "INACTIVE"
}

# The three development logins are left without a record for *today*, so that
# signing in as jane and pressing Check In actually does something. Everyone
# else gets today filled in, which is what makes the "present today" and
# "missing checkout" tiles non-zero.
LIVE_DEMO_EMPLOYEE_CODES = {"EMP-003", "EMP-004", "EMP-005"}


@dataclass(frozen=True)
class AttendanceSeed:
    employee_code: str
    attendance_date: date
    check_in: datetime | None
    check_out: datetime | None
    # Only set for days no timestamp could explain - away on approved leave, or
    # absent. Everything else is derived from the two times by the same
    # function the API uses.
    status_override: str | None
    remarks: str | None


@dataclass(frozen=True)
class TimesheetSeed:
    employee_code: str
    work_date: date
    minutes: int
    work_description: str
    reference: str | None
    state_code: str


# What people say they were doing. A small rotating vocabulary - enough that
# the screens do not look like one row copied twenty times, and not so much
# that it pretends to be a real project taxonomy.
_WORK_ITEMS: list[tuple[str, str | None]] = [
    ("Feature development on the customer portal", "PRJ-101"),
    ("Bug triage and fixes from the support queue", "PRJ-102"),
    ("Code review and pairing with the team", "PRJ-101"),
    ("Release preparation and regression checks", "PRJ-103"),
    ("Documentation and handover notes", "PRJ-104"),
    ("Client meeting and follow-up actions", "PRJ-105"),
    ("Data reconciliation and reporting", "PRJ-106"),
    ("Onboarding support for a new joiner", None),
]


def _local(day: date, minutes_past_midnight: int) -> datetime:
    """A wall-clock time on a given day, in the server's local timezone."""
    moment = datetime.combine(
        day, time(hour=minutes_past_midnight // 60, minute=minutes_past_midnight % 60)
    )
    return moment.astimezone()


def _working_days(end: date, count: int) -> list[date]:
    """
    The last `count` weekdays up to and including `end`.

    Weekends are skipped here purely to make the fixture data look like a real
    working month. It is **not** a business rule: nothing in the platform knows
    what a weekend is, and the worked-hours calculation is plain elapsed time.
    A holiday calendar is a later stage.
    """
    days, cursor = [], end
    while len(days) < count:
        if cursor.weekday() < 5:        # Monday-Friday
            days.append(cursor)
        cursor -= timedelta(days=1)
    return sorted(days)


def build_attendance_rows(today: date) -> list[AttendanceSeed]:
    """
    Deterministic attendance for the seeded workforce.

    Seeded from the employee code and the date, so the same day always produces
    the same record however often the seed runs - that is what makes the
    fixture idempotent without storing a random seed anywhere.

    The mix is chosen so every status is represented and the dashboard has
    something to show: mostly full days, with a few half days, a few absences,
    and - importantly - some people who checked in and never checked out. That
    last group is the one a manager is meant to chase, so it has to exist.
    """
    rows: list[AttendanceSeed] = []

    for employee in EMPLOYEES:
        if employee.code in INACTIVE_EMPLOYEE_CODES:
            continue

        for day in _working_days(today, ATTENDANCE_HISTORY_DAYS):
            if day == today and employee.code in LIVE_DEMO_EMPLOYEE_CODES:
                continue        # left open so the demo user can check in

            rng = random.Random(f"attendance:{employee.code}:{day.isoformat()}")
            roll = rng.random()

            if day == today:
                # Today is still in progress: everybody who is in has checked
                # in, and nobody has gone home yet.
                rows.append(AttendanceSeed(
                    employee.code, day,
                    _local(day, rng.randint(8 * 60 + 40, 9 * 60 + 20)),
                    None, None, None,
                ))
                continue

            if roll < 0.80:
                check_in = rng.randint(8 * 60 + 40, 9 * 60 + 25)
                rows.append(AttendanceSeed(
                    employee.code, day,
                    _local(day, check_in),
                    _local(day, check_in + rng.randint(8 * 60, 9 * 60 + 30)),
                    None, None,
                ))
            elif roll < 0.87:
                check_in = rng.randint(8 * 60 + 45, 9 * 60 + 15)
                rows.append(AttendanceSeed(
                    employee.code, day,
                    _local(day, check_in),
                    _local(day, check_in + rng.randint(150, 230)),
                    None, "Left early.",
                ))
            elif roll < 0.93:
                # Checked in and never checked out - the row a manager chases.
                rows.append(AttendanceSeed(
                    employee.code, day,
                    _local(day, rng.randint(8 * 60 + 45, 9 * 60 + 20)),
                    None, None, "No checkout recorded.",
                ))
            elif roll < 0.97:
                rows.append(AttendanceSeed(
                    employee.code, day, None, None, "ON_LEAVE", "Approved leave.",
                ))
            else:
                rows.append(AttendanceSeed(
                    employee.code, day, None, None, "ABSENT", "Unplanned absence.",
                ))

    return rows


def build_timesheet_rows(today: date) -> list[TimesheetSeed]:
    """
    Deterministic timesheets, at most one entry per employee per day.

    The table allows many entries a day - a real day is several pieces of work -
    but the fixture keeps to one so that (employee, date) is a natural key the
    seed can match on and re-running changes nothing.

    States are spread deliberately: older work has been approved, the most
    recent week is still waiting on a review, a couple have been rejected and
    are back with their author, and the last few days are still drafts.
    """
    rows: list[TimesheetSeed] = []

    for employee in EMPLOYEES:
        if employee.code in INACTIVE_EMPLOYEE_CODES:
            continue

        for day in _working_days(today, TIMESHEET_HISTORY_DAYS):
            rng = random.Random(f"timesheet:{employee.code}:{day.isoformat()}")

            # Not every person logs work every day.
            if rng.random() < 0.45:
                continue

            description, reference = _WORK_ITEMS[rng.randrange(len(_WORK_ITEMS))]
            minutes = rng.choice([180, 240, 300, 360, 420, 450, 480])
            age = (today - day).days

            if age >= 10:
                state = "APPROVED" if rng.random() < 0.85 else "REJECTED"
            elif age >= 3:
                state = "SUBMITTED" if rng.random() < 0.75 else "APPROVED"
            else:
                state = "DRAFT"

            rows.append(TimesheetSeed(
                employee.code, day, minutes, description, reference, state,
            ))

    return rows

# ---------------------------------------------------------------------------
# Expense Management (Stage 11)
# ---------------------------------------------------------------------------

EXPENSE_HISTORY_DAYS = 90
EXPENSE_CURRENCY = "USD"


@dataclass(frozen=True)
class ExpenseCategorySeed:
    code: str
    name: str
    description: str
    display_order: int


@dataclass(frozen=True)
class ExpenseSeed:
    employee_code: str
    category_code: str
    expense_date: date
    amount: str          # a decimal string; never a float, see the model
    merchant: str
    description: str
    reference_number: str | None
    state_code: str


# The kinds of expense, as rows. Adding "Client Entertainment" is one more
# line here and an INSERT in the database - no enum, no migration, and no
# change to the React form, which builds its dropdown from the API.
EXPENSE_CATEGORIES: list[ExpenseCategorySeed] = [
    ExpenseCategorySeed("TRAVEL", "Travel",
                        "Flights, rail and long-distance travel.", 1),
    ExpenseCategorySeed("TRANSPORT", "Local Transport",
                        "Taxis, mileage and public transport.", 2),
    ExpenseCategorySeed("HOTEL", "Hotel",
                        "Overnight accommodation while travelling.", 3),
    ExpenseCategorySeed("MEALS", "Meals",
                        "Subsistence while working away.", 4),
    ExpenseCategorySeed("OFFICE_SUPPLIES", "Office Supplies",
                        "Stationery, peripherals and small equipment.", 5),
    ExpenseCategorySeed("COMMUNICATION", "Communication",
                        "Phone, mobile data and conferencing.", 6),
    ExpenseCategorySeed("TRAINING", "Training",
                        "Courses, certifications and conference fees.", 7),
    ExpenseCategorySeed("OTHER", "Other",
                        "Anything that does not fit the categories above.", 8),
]

# Merchants and descriptions that read like a real expense report, keyed by
# category so a hotel claim is not filed against a taxi firm.
_EXPENSE_DETAIL: dict[str, list[tuple[str, str]]] = {
    "TRAVEL": [
        ("Northwind Air", "Return flight for the quarterly review."),
        ("Continental Rail", "Rail fare to the client site."),
    ],
    "TRANSPORT": [
        ("City Cabs", "Taxi from the airport to the office."),
        ("Metro Transit", "Travel card for the week on site."),
    ],
    "HOTEL": [
        ("Grand Central Hotel", "Two nights during the client workshop."),
        ("Riverside Inn", "One night before an early start."),
    ],
    "MEALS": [
        ("The Corner Bistro", "Evening meal while working away."),
        ("Station Cafe", "Lunch during an all-day workshop."),
    ],
    "OFFICE_SUPPLIES": [
        ("Paperworks Ltd", "Notebooks and stationery for the team."),
        ("TechDirect", "Replacement keyboard and mouse."),
    ],
    "COMMUNICATION": [
        ("Telecom One", "Monthly mobile data allowance."),
        ("ConferenceCo", "Video conferencing licence."),
    ],
    "TRAINING": [
        ("SkillBridge", "Online course on data modelling."),
        ("DevConf", "Conference ticket and materials."),
    ],
    "OTHER": [
        ("Postal Express", "Courier for signed contracts."),
        ("City Parking", "Parking during a client visit."),
    ],
}

# Roughly what each category costs, as (minimum, maximum) whole units. Kept
# plausible so the charts have a believable shape - a hotel outweighs a
# coffee, and Travel dominates the category chart the way it usually does.
_EXPENSE_RANGE: dict[str, tuple[int, int]] = {
    "TRAVEL": (180, 950),
    "TRANSPORT": (12, 85),
    "HOTEL": (110, 420),
    "MEALS": (9, 65),
    "OFFICE_SUPPLIES": (15, 240),
    "COMMUNICATION": (20, 95),
    "TRAINING": (150, 1200),
    "OTHER": (8, 140),
}


def build_expense_rows(today: date) -> list[ExpenseSeed]:
    """
    Deterministic expense claims for the seeded workforce.

    Seeded from the employee code and the date, like the attendance and
    timesheet fixtures, so the same day always produces the same claims and
    re-running the seed changes nothing.

    States are spread by age, which is what a real expense report looks like:
    old claims have been settled, the last fortnight is still waiting on
    somebody, a few were rejected and are back with their claimant, and the
    newest are drafts that have not been sent yet. One is cancelled, because a
    withdrawn claim is a state the screens have to render too.
    """
    rows: list[ExpenseSeed] = []
    category_codes = [category.code for category in EXPENSE_CATEGORIES]

    for employee in EMPLOYEES:
        if employee.code in INACTIVE_EMPLOYEE_CODES:
            continue

        for offset in range(0, EXPENSE_HISTORY_DAYS, 3):
            day = today - timedelta(days=offset)
            if day.weekday() >= 5:
                continue

            rng = random.Random(f"expense:{employee.code}:{day.isoformat()}")
            # Expenses are occasional, not daily.
            if rng.random() < 0.80:
                continue

            category = category_codes[rng.randrange(len(category_codes))]
            merchant, description = _EXPENSE_DETAIL[category][rng.randrange(2)]
            low, high = _EXPENSE_RANGE[category]
            # Two decimal places, built as a string so no float ever touches a
            # money value on its way into the database.
            amount = f"{rng.randint(low, high)}.{rng.randrange(0, 100):02d}"

            if offset >= 45:
                state = "APPROVED" if rng.random() < 0.88 else "REJECTED"
            elif offset >= 30:
                state = "APPROVED" if rng.random() < 0.55 else "CANCELLED"
            elif offset >= 6:
                state = "SUBMITTED" if rng.random() < 0.80 else "APPROVED"
            else:
                state = "DRAFT"

            rows.append(ExpenseSeed(
                employee_code=employee.code,
                category_code=category,
                expense_date=day,
                amount=amount,
                merchant=merchant,
                description=description,
                reference_number=f"RCT-{rng.randrange(100000, 999999)}",
                state_code=state,
            ))

    return rows

@dataclass(frozen=True)
class BusinessUnitTypeSeed:
    code: str
    name: str
    description: str
    display_order: int


@dataclass(frozen=True)
class BusinessUnitSeed:
    code: str
    name: str
    type_code: str
    # None marks a root of the tree. Every other unit names its parent by code,
    # so this list reads like the org chart it describes.
    parent_code: str | None


# The kinds of unit an organisation has. Rows, not a Python enum - an
# organisation that also needs "Region" adds a row and changes no code.
# display_order doubles as the depth ranking of the type.
BUSINESS_UNIT_TYPES: list[BusinessUnitTypeSeed] = [
    BusinessUnitTypeSeed("HEADQUARTERS", "Headquarters",
                         "The top of the organisation.", 1),
    BusinessUnitTypeSeed("COMPANY", "Company", "A legal entity.", 2),
    BusinessUnitTypeSeed("BRANCH", "Branch", "A location or site.", 3),
    BusinessUnitTypeSeed("DEPARTMENT", "Department", "A team within a branch.", 4),
]

# The development organisation tree:
#
#   Headquarters
#   |-- Company 1
#   |     |-- Branch 1 -- Department 1, Department 2
#   |     +-- Branch 2 -- Department 3, Department 4
#   +-- Company 2
#         +-- Branch 3 -- Department 5, Department 6
BUSINESS_UNITS: list[BusinessUnitSeed] = [
    BusinessUnitSeed("HQ", "Headquarters", "HEADQUARTERS", None),

    BusinessUnitSeed("COMPANY_1", "Company 1", "COMPANY", "HQ"),
    BusinessUnitSeed("BRANCH_1", "Branch 1", "BRANCH", "COMPANY_1"),
    BusinessUnitSeed("DEPARTMENT_1", "Department 1", "DEPARTMENT", "BRANCH_1"),
    BusinessUnitSeed("DEPARTMENT_2", "Department 2", "DEPARTMENT", "BRANCH_1"),
    BusinessUnitSeed("BRANCH_2", "Branch 2", "BRANCH", "COMPANY_1"),
    BusinessUnitSeed("DEPARTMENT_3", "Department 3", "DEPARTMENT", "BRANCH_2"),
    BusinessUnitSeed("DEPARTMENT_4", "Department 4", "DEPARTMENT", "BRANCH_2"),

    BusinessUnitSeed("COMPANY_2", "Company 2", "COMPANY", "HQ"),
    BusinessUnitSeed("BRANCH_3", "Branch 3", "BRANCH", "COMPANY_2"),
    BusinessUnitSeed("DEPARTMENT_5", "Department 5", "DEPARTMENT", "BRANCH_3"),
    BusinessUnitSeed("DEPARTMENT_6", "Department 6", "DEPARTMENT", "BRANCH_3"),
]

# Where the development users sit in the organisation. Each assignment also
# grants everything below it, so these four cover every depth of the tree.
#
# Add-only: a person's own assignments are not the seed's business to remove,
# so changes made through the admin screen survive a re-run.
DEV_USER_BUSINESS_UNITS: dict[str, list[str]] = {
    "admin": ["HQ"],            # sees the whole organisation
    "priya": ["COMPANY_1"],     # HR      - Company 1 and everything under it
    "raj": ["BRANCH_1"],        # Manager - Branch 1, Departments 1 and 2
    "jane": ["DEPARTMENT_1"],   # Employee - Department 1 only
}


@dataclass(frozen=True)
class WorkflowSeed:
    code: str
    name: str
    description: str
    application_code: str | None


@dataclass(frozen=True)
class WorkflowStateSeed:
    workflow_code: str
    code: str
    name: str
    is_initial: bool
    is_final: bool
    display_order: int
    # While a record sits in this state, is it on the desk of the person who
    # raised it? Applications read this to tell an owner's action from an
    # approver's; the engine itself never looks at it. Defaults to False, so
    # the demo workflow keeps behaving exactly as it did.
    is_owner_held: bool = False


@dataclass(frozen=True)
class WorkflowTransitionSeed:
    workflow_code: str
    code: str
    name: str
    from_state_code: str
    to_state_code: str
    # Which RBAC roles may perform it. This is the whole authorisation rule -
    # the engine holds no role names of its own.
    role_codes: list[str]
    # Who performs it, relative to the record: OWNER, OTHER, or ANY.
    #
    # Roles and actor answer different questions and both are needed. MANAGER
    # may approve expenses (role), but not their own (actor OTHER). ANY is the
    # default, so the Stage 7 demo workflow is unaffected.
    actor: str = "ANY"


# The demonstration workflow. It belongs to no application (application_code is
# None) because it exists to exercise the engine, not to be part of Expense
# Management - that application is built in a later stage.
WORKFLOWS: list[WorkflowSeed] = [
    WorkflowSeed(
        "EXPENSE_APPROVAL_DEMO",
        "Expense Approval Demo",
        "A small two-step approval used to demonstrate the generic workflow "
        "engine. Not part of Expense Management.",
        None,
    ),
    # The first workflow behind a real application. Nothing about the engine
    # changes to support it - this is rows, not code.
    WorkflowSeed(
        "LEAVE_APPROVAL",
        "Leave Approval",
        "How a leave request travels from draft to a decision.",
        "LEAVE_MANAGEMENT",
    ),
    # The second real workflow, and the one that proves the engine generalises:
    # it has a *loop* back to the beginning, which leave does not.
    WorkflowSeed(
        "TIMESHEET_APPROVAL",
        "Timesheet Approval",
        "How recorded work is submitted, reviewed and, if rejected, revised.",
        "ATTENDANCE_TIMESHEET",
    ),
    WorkflowSeed(
        "EXPENSE_APPROVAL",
        "Expense Approval",
        "How an expense claim is submitted, reviewed, and withdrawn or revised.",
        "EXPENSE_MANAGEMENT",
    ),
]

WORKFLOW_STATES: list[WorkflowStateSeed] = [
    WorkflowStateSeed("EXPENSE_APPROVAL_DEMO", "DRAFT", "Draft",
                      is_initial=True, is_final=False, display_order=1),
    WorkflowStateSeed("EXPENSE_APPROVAL_DEMO", "PENDING_MANAGER_APPROVAL",
                      "Pending Manager Approval",
                      is_initial=False, is_final=False, display_order=2),
    WorkflowStateSeed("EXPENSE_APPROVAL_DEMO", "APPROVED", "Approved",
                      is_initial=False, is_final=True, display_order=3),
    WorkflowStateSeed("EXPENSE_APPROVAL_DEMO", "REJECTED", "Rejected",
                      is_initial=False, is_final=True, display_order=4),

    # Leave. `is_initial` is what the leave service reads to decide whether a
    # request may still be edited, and `is_final` is what tells the approval
    # queue a request is settled - neither rule names a state.
    WorkflowStateSeed("LEAVE_APPROVAL", "DRAFT", "Draft",
                      is_initial=True, is_final=False, display_order=1,
                      is_owner_held=True),
    WorkflowStateSeed("LEAVE_APPROVAL", "PENDING_APPROVAL", "Pending Approval",
                      is_initial=False, is_final=False, display_order=2),
    WorkflowStateSeed("LEAVE_APPROVAL", "APPROVED", "Approved",
                      is_initial=False, is_final=True, display_order=3),
    WorkflowStateSeed("LEAVE_APPROVAL", "REJECTED", "Rejected",
                      is_initial=False, is_final=True, display_order=4),
    WorkflowStateSeed("LEAVE_APPROVAL", "CANCELLED", "Cancelled",
                      is_initial=False, is_final=True, display_order=5),

    # Timesheets. Two states are owner-held rather than one: a rejected entry
    # comes back to its author to revise, so Revise is offered to them and not
    # to the manager who rejected it. Note REJECTED is NOT final - something
    # still leaves it - which is the difference from the leave workflow.
    WorkflowStateSeed("TIMESHEET_APPROVAL", "DRAFT", "Draft",
                      is_initial=True, is_final=False, display_order=1,
                      is_owner_held=True),
    WorkflowStateSeed("TIMESHEET_APPROVAL", "SUBMITTED", "Submitted",
                      is_initial=False, is_final=False, display_order=2),
    WorkflowStateSeed("TIMESHEET_APPROVAL", "APPROVED", "Approved",
                      is_initial=False, is_final=True, display_order=3),
    WorkflowStateSeed("TIMESHEET_APPROVAL", "REJECTED", "Rejected",
                      is_initial=False, is_final=False, display_order=4,
                      is_owner_held=True),

    # Expenses. SUBMITTED is NOT owner-held: a submitted claim is genuinely on
    # the approver's desk, which is what the pending queue counts. Cancel
    # still belongs to the claimant, and that is recorded on the transition.
    WorkflowStateSeed("EXPENSE_APPROVAL", "DRAFT", "Draft",
                      is_initial=True, is_final=False, display_order=1,
                      is_owner_held=True),
    WorkflowStateSeed("EXPENSE_APPROVAL", "SUBMITTED", "Submitted",
                      is_initial=False, is_final=False, display_order=2),
    WorkflowStateSeed("EXPENSE_APPROVAL", "APPROVED", "Approved",
                      is_initial=False, is_final=True, display_order=3),
    WorkflowStateSeed("EXPENSE_APPROVAL", "REJECTED", "Rejected",
                      is_initial=False, is_final=False, display_order=4,
                      is_owner_held=True),
    WorkflowStateSeed("EXPENSE_APPROVAL", "CANCELLED", "Cancelled",
                      is_initial=False, is_final=True, display_order=5),
]

# Note what is NOT here: there is no DRAFT -> APPROVED row, which is precisely
# why the engine refuses that jump.
WORKFLOW_TRANSITIONS: list[WorkflowTransitionSeed] = [
    WorkflowTransitionSeed(
        "EXPENSE_APPROVAL_DEMO", "SUBMIT", "Submit",
        "DRAFT", "PENDING_MANAGER_APPROVAL", ["EMPLOYEE"],
    ),
    WorkflowTransitionSeed(
        "EXPENSE_APPROVAL_DEMO", "APPROVE", "Approve",
        "PENDING_MANAGER_APPROVAL", "APPROVED", ["MANAGER"],
    ),
    WorkflowTransitionSeed(
        "EXPENSE_APPROVAL_DEMO", "REJECT", "Reject",
        "PENDING_MANAGER_APPROVAL", "REJECTED", ["MANAGER"],
    ),

    # --- Leave Approval ---------------------------------------------------
    #
    # Two layers decide who may act, and they are different questions:
    #
    #   role_codes below  - WHICH ROLES may ever perform this transition
    #   the leave service - WHETHER THIS CALLER is the right person for it
    #
    # Submit and Cancel list every role that can own leave, because anyone may
    # submit their *own* request; the service then requires ownership. Approve
    # and Reject list the approving roles, and the service requires that the
    # caller is *not* the owner, which is what forbids self-approval.
    WorkflowTransitionSeed(
        "LEAVE_APPROVAL", "SUBMIT", "Submit",
        "DRAFT", "PENDING_APPROVAL",
        ["EMPLOYEE", "MANAGER", "HR", "SUPER_ADMIN"], actor="OWNER",
    ),
    WorkflowTransitionSeed(
        "LEAVE_APPROVAL", "CANCEL", "Cancel",
        "DRAFT", "CANCELLED",
        ["EMPLOYEE", "MANAGER", "HR", "SUPER_ADMIN"], actor="OWNER",
    ),
    WorkflowTransitionSeed(
        "LEAVE_APPROVAL", "APPROVE", "Approve",
        "PENDING_APPROVAL", "APPROVED",
        ["MANAGER", "HR", "SUPER_ADMIN"], actor="OTHER",
    ),
    WorkflowTransitionSeed(
        "LEAVE_APPROVAL", "REJECT", "Reject",
        "PENDING_APPROVAL", "REJECTED",
        ["MANAGER", "HR", "SUPER_ADMIN"], actor="OTHER",
    ),

    # --- Timesheet Approval -----------------------------------------------
    #
    # As with leave, two layers decide who may act and they answer different
    # questions: role_codes below say WHICH ROLES may ever perform the
    # transition, and the service then asks WHETHER THIS CALLER is the right
    # person - which it reads from the from-state's is_owner_held flag.
    #
    # Revise is the interesting one. It carries the same roles as Submit
    # because it is the author's action, and the metadata says so by starting
    # it from REJECTED, which is owner-held.
    WorkflowTransitionSeed(
        "TIMESHEET_APPROVAL", "SUBMIT", "Submit",
        "DRAFT", "SUBMITTED",
        ["EMPLOYEE", "MANAGER", "HR", "SUPER_ADMIN"], actor="OWNER",
    ),
    WorkflowTransitionSeed(
        "TIMESHEET_APPROVAL", "APPROVE", "Approve",
        "SUBMITTED", "APPROVED",
        ["MANAGER", "HR", "SUPER_ADMIN"], actor="OTHER",
    ),
    WorkflowTransitionSeed(
        "TIMESHEET_APPROVAL", "REJECT", "Reject",
        "SUBMITTED", "REJECTED",
        ["MANAGER", "HR", "SUPER_ADMIN"], actor="OTHER",
    ),
    WorkflowTransitionSeed(
        "TIMESHEET_APPROVAL", "REVISE", "Revise",
        "REJECTED", "DRAFT",
        ["EMPLOYEE", "MANAGER", "HR", "SUPER_ADMIN"], actor="OWNER",
    ),

    # --- Expense Approval -------------------------------------------------
    #
    # Cancel is why `actor` lives on the transition rather than on the state
    # it leaves. An expense in SUBMITTED sits on the approver's desk, which is
    # exactly what the pending queue needs SUBMITTED to mean - and yet Cancel,
    # the claimant withdrawing their own claim, leaves that same state and is
    # theirs. No state-level flag can say both things at once.
    WorkflowTransitionSeed(
        "EXPENSE_APPROVAL", "SUBMIT", "Submit",
        "DRAFT", "SUBMITTED",
        ["EMPLOYEE", "MANAGER", "HR", "SUPER_ADMIN"], actor="OWNER",
    ),
    WorkflowTransitionSeed(
        "EXPENSE_APPROVAL", "CANCEL", "Cancel",
        "SUBMITTED", "CANCELLED",
        ["EMPLOYEE", "MANAGER", "HR", "SUPER_ADMIN"], actor="OWNER",
    ),
    WorkflowTransitionSeed(
        "EXPENSE_APPROVAL", "APPROVE", "Approve",
        "SUBMITTED", "APPROVED",
        ["MANAGER", "HR", "SUPER_ADMIN"], actor="OTHER",
    ),
    WorkflowTransitionSeed(
        "EXPENSE_APPROVAL", "REJECT", "Reject",
        "SUBMITTED", "REJECTED",
        ["MANAGER", "HR", "SUPER_ADMIN"], actor="OTHER",
    ),
    WorkflowTransitionSeed(
        "EXPENSE_APPROVAL", "REVISE", "Revise",
        "REJECTED", "DRAFT",
        ["EMPLOYEE", "MANAGER", "HR", "SUPER_ADMIN"], actor="OWNER",
    ),
]


# ---------------------------------------------------------------------------
# 2. Who gets what
# ---------------------------------------------------------------------------

ROLE_PERMISSIONS: dict[str, list[str] | str] = {
    "SUPER_ADMIN": ALL,
    # CONFIGURE alone is not enough to administer the platform: the management
    # endpoints also require access to a platform-admin application, which this
    # role does not receive by default.
    "APPLICATION_ADMIN": ["VIEW", "CONFIGURE"],
    "HR": ["VIEW", "CREATE", "EDIT", "EXPORT", "APPROVE"],
    "MANAGER": ["VIEW", "APPROVE", "EXPORT"],
    "EMPLOYEE": ["VIEW"],
}

# Which applications each role can open.
#
# Two rules worth stating explicitly, because both are easy to get wrong:
#
#   * Employee Management is an HR/management application, NOT self-service.
#     An ordinary EMPLOYEE has no access to it.
#   * Payroll IS employee-facing - everyone needs to see their own salary.
#     Opening the application is not the same as seeing everybody's data;
#     row-level filtering arrives with the payroll feature itself.
#
# Only SUPER_ADMIN receives the three platform-admin applications.
ROLE_APPLICATIONS: dict[str, list[str] | str] = {
    "SUPER_ADMIN": ALL,
    # Application-scoped: an administrator assigns the applications this role
    # may configure, so it starts empty rather than receiving everything.
    "APPLICATION_ADMIN": [],
    "HR": ["EMPLOYEE_MANAGEMENT", "LEAVE_MANAGEMENT", "PAYROLL",
           "ATTENDANCE_TIMESHEET", "EXPENSE_MANAGEMENT"],
    "MANAGER": ["EMPLOYEE_MANAGEMENT", "LEAVE_MANAGEMENT", "PAYROLL",
                "ATTENDANCE_TIMESHEET", "EXPENSE_MANAGEMENT"],
    "EMPLOYEE": ["LEAVE_MANAGEMENT", "PAYROLL",
                 "ATTENDANCE_TIMESHEET", "EXPENSE_MANAGEMENT"],
}

# By default a role gets every screen of every application it can open.
# These screens are then taken back off specific roles, which is what makes
# screen access genuinely independent of application access.
ROLE_SCREEN_EXCLUSIONS: dict[str, list[str]] = {
    # An employee uses the "My ..." screens. Management dashboards and the
    # approval screens belong to managers, HR and administrators.
    "EMPLOYEE": [
        "LEAVE_DASHBOARD",
        "LEAVE_APPROVAL",
        "PAYROLL_DASHBOARD",
        "SALARY_COMPONENTS",
        "ATTENDANCE_DASHBOARD",
        "TEAM_ATTENDANCE",
        "TIMESHEET_APPROVAL",
        "EXPENSE_DASHBOARD",
        "EXPENSE_APPROVAL",
    ],
    # A manager approves their team's requests and sees the team dashboards,
    # but payroll administration is still not theirs.
    "MANAGER": ["PAYROLL_DASHBOARD", "SALARY_COMPONENTS"],
}

# The local admin user becomes a Super Admin.
ADMIN_ROLES = ["SUPER_ADMIN"]


# ---------------------------------------------------------------------------
# 3. Applying it
# ---------------------------------------------------------------------------


def _reconcile(collection: list, wanted: list) -> int:
    """
    Make a relationship list match `wanted` exactly.

    Adds what is missing and removes what should no longer be there, returning
    how many changes were made. The removal half is what lets a correction to
    this file take effect - without it, a role could never lose access.
    """
    changes = 0
    for item in wanted:
        if item not in collection:
            collection.append(item)
            changes += 1
    for item in list(collection):
        if item not in wanted:
            collection.remove(item)
            changes += 1
    return changes


def _history_actor(db: Session, employee: Employee) -> User | None:
    """
    Whose name goes on a seeded history row.

    The employee's own login where they have one, otherwise the local admin
    account, otherwise nobody - in which case the caller skips the history
    rather than inventing a user. Most seeded employees have no login at all,
    which is the normal case for HR records.
    """
    if employee.user_id is not None:
        return db.get(User, employee.user_id)
    return db.scalar(select(User).where(User.username == ADMIN_USERNAME))


def _seed_leave_history(
    db: Session,
    request: LeaveRequest,
    seed: "LeaveRequestSeed",
    employees: dict[str, Employee],
    workflow_states: dict[tuple[str, str], WorkflowState],
    workflow_transitions: dict[tuple[str, str], WorkflowTransition],
) -> int:
    """
    Give a seeded request the trail it would have had if a person had driven it.

    Seeded rows are written straight into their final state - they never pass
    through the engine, because the engine needs a signed-in user performing a
    real action. Writing the matching history by hand keeps the demo honest:
    an approved request can show who approved it, and the Approval screen is
    not full of records with an empty timeline.

    Nothing here changes the engine's rule that a *real* transition and its
    history row commit together. This is fixture data being made consistent,
    not a second way to move a record.
    """
    # Idempotent: a request that already has a trail is left exactly as it is.
    existing = db.scalar(
        select(func.count())
        .select_from(WorkflowHistory)
        .where(
            WorkflowHistory.entity_type == LeaveRequest.__tablename__,
            WorkflowHistory.entity_id == request.id,
        )
    )
    if existing:
        return 0

    employee = employees[seed.employee_code]
    owner = _history_actor(db, employee)
    if owner is None:
        return 0        # no account to attribute anything to - skip quietly

    # The approver is the employee's manager if they have a login, else the
    # same fallback the owner used.
    approver = owner
    if employee.manager_id is not None:
        manager = db.get(Employee, employee.manager_id)
        if manager is not None:
            approver = _history_actor(db, manager) or owner

    def state(code: str) -> WorkflowState:
        return workflow_states[("LEAVE_APPROVAL", code)]

    def transition(code: str) -> WorkflowTransition:
        return workflow_transitions[("LEAVE_APPROVAL", code)]

    # Every request begins in Draft with an opening row that has no "from" and
    # no transition - it did not move there, it started there.
    steps: list[tuple[WorkflowState | None, WorkflowState, WorkflowTransition | None, User, str]] = [
        (None, state("DRAFT"), None, owner, "Request created."),
    ]

    if seed.state_code == "CANCELLED":
        steps.append(
            (state("DRAFT"), state("CANCELLED"), transition("CANCEL"), owner,
             "Cancelled by the employee before submission.")
        )
    elif seed.state_code != "DRAFT":
        steps.append(
            (state("DRAFT"), state("PENDING_APPROVAL"), transition("SUBMIT"),
             owner, "Submitted for approval.")
        )
        if seed.state_code == "APPROVED":
            steps.append(
                (state("PENDING_APPROVAL"), state("APPROVED"),
                 transition("APPROVE"), approver, "Approved.")
            )
        elif seed.state_code == "REJECTED":
            steps.append(
                (state("PENDING_APPROVAL"), state("REJECTED"),
                 transition("REJECT"), approver,
                 "Rejected - cover could not be arranged.")
            )

    for from_state, to_state, used, actor, comment in steps:
        db.add(
            WorkflowHistory(
                workflow_id=request.workflow_id,
                entity_type=LeaveRequest.__tablename__,
                entity_id=request.id,
                from_state_id=None if from_state is None else from_state.id,
                to_state_id=to_state.id,
                transition_id=None if used is None else used.id,
                performed_by_user_id=actor.id,
                comments=comment,
            )
        )
    return len(steps)


def _seed_timesheet_history(
    db: Session,
    entry: Timesheet,
    seed: "TimesheetSeed",
    employees: dict[str, Employee],
    workflow_states: dict[tuple[str, str], WorkflowState],
    workflow_transitions: dict[tuple[str, str], WorkflowTransition],
) -> int:
    """
    Give a seeded timesheet the trail it would have had if a person had driven it.

    Exactly the same reasoning as the leave fixtures: seeded rows are written
    straight into their final state, because the engine needs a signed-in user
    performing a real action. Writing the matching history by hand keeps the
    demo honest - an approved entry can show who approved it, and the approval
    screen is not full of records with an empty timeline.

    This is fixture data being made consistent, not a second way to move a
    record. A real transition still goes through the engine, which writes the
    state and the history row in one transaction.
    """
    existing = db.scalar(
        select(func.count())
        .select_from(WorkflowHistory)
        .where(
            WorkflowHistory.entity_type == Timesheet.__tablename__,
            WorkflowHistory.entity_id == entry.id,
        )
    )
    if existing:
        return 0

    employee = employees[seed.employee_code]
    owner = _history_actor(db, employee)
    if owner is None:
        return 0        # no account to attribute anything to - skip quietly

    approver = owner
    if employee.manager_id is not None:
        manager = db.get(Employee, employee.manager_id)
        if manager is not None:
            approver = _history_actor(db, manager) or owner

    def state(code: str) -> WorkflowState:
        return workflow_states[("TIMESHEET_APPROVAL", code)]

    def transition(code: str) -> WorkflowTransition:
        return workflow_transitions[("TIMESHEET_APPROVAL", code)]

    steps: list[tuple[WorkflowState | None, WorkflowState,
                      WorkflowTransition | None, User, str]] = [
        (None, state("DRAFT"), None, owner, "Entry created."),
    ]

    if seed.state_code != "DRAFT":
        steps.append(
            (state("DRAFT"), state("SUBMITTED"), transition("SUBMIT"), owner,
             "Submitted for review.")
        )
        if seed.state_code == "APPROVED":
            steps.append(
                (state("SUBMITTED"), state("APPROVED"), transition("APPROVE"),
                 approver, "Approved.")
            )
        elif seed.state_code == "REJECTED":
            steps.append(
                (state("SUBMITTED"), state("REJECTED"), transition("REJECT"),
                 approver, "Rejected - please add more detail and resubmit.")
            )

    for from_state, to_state, used, actor, comment in steps:
        db.add(
            WorkflowHistory(
                workflow_id=entry.workflow_id,
                entity_type=Timesheet.__tablename__,
                entity_id=entry.id,
                from_state_id=None if from_state is None else from_state.id,
                to_state_id=to_state.id,
                transition_id=None if used is None else used.id,
                performed_by_user_id=actor.id,
                comments=comment,
            )
        )
    return len(steps)


def _seed_expense_history(
    db: Session,
    expense: Expense,
    seed: "ExpenseSeed",
    employees: dict[str, Employee],
    workflow_states: dict[tuple[str, str], WorkflowState],
    workflow_transitions: dict[tuple[str, str], WorkflowTransition],
) -> int:
    """
    Give a seeded claim the trail it would have had if a person had driven it.

    The same reasoning as the leave and timesheet fixtures: seeded rows are
    written straight into their final state, because the engine needs a
    signed-in user performing a real action. Writing the matching history by
    hand keeps the demo honest - an approved claim can say who approved it,
    and a rejected one carries the reason.

    This is fixture data being made consistent, not a second way to move a
    record. A real transition still goes through the engine, which writes the
    state and the history row in one transaction.
    """
    existing = db.scalar(
        select(func.count())
        .select_from(WorkflowHistory)
        .where(
            WorkflowHistory.entity_type == Expense.__tablename__,
            WorkflowHistory.entity_id == expense.id,
        )
    )
    if existing:
        return 0

    employee = employees[seed.employee_code]
    owner = _history_actor(db, employee)
    if owner is None:
        return 0

    approver = owner
    if employee.manager_id is not None:
        manager = db.get(Employee, employee.manager_id)
        if manager is not None:
            approver = _history_actor(db, manager) or owner

    def state(code: str) -> WorkflowState:
        return workflow_states[("EXPENSE_APPROVAL", code)]

    def transition(code: str) -> WorkflowTransition:
        return workflow_transitions[("EXPENSE_APPROVAL", code)]

    steps: list[tuple[WorkflowState | None, WorkflowState,
                      WorkflowTransition | None, User, str]] = [
        (None, state("DRAFT"), None, owner, "Claim created."),
    ]

    if seed.state_code != "DRAFT":
        steps.append(
            (state("DRAFT"), state("SUBMITTED"), transition("SUBMIT"), owner,
             "Submitted for approval.")
        )
        if seed.state_code == "APPROVED":
            steps.append(
                (state("SUBMITTED"), state("APPROVED"), transition("APPROVE"),
                 approver, "Approved for reimbursement.")
            )
        elif seed.state_code == "REJECTED":
            steps.append(
                (state("SUBMITTED"), state("REJECTED"), transition("REJECT"),
                 approver, "Rejected - please attach the itemised receipt.")
            )
        elif seed.state_code == "CANCELLED":
            # Cancelled by the claimant, not the approver. That is the whole
            # reason `actor` lives on the transition rather than the state.
            steps.append(
                (state("SUBMITTED"), state("CANCELLED"), transition("CANCEL"),
                 owner, "Withdrawn by the claimant.")
            )

    for from_state, to_state, used, actor, comment in steps:
        db.add(
            WorkflowHistory(
                workflow_id=expense.workflow_id,
                entity_type=Expense.__tablename__,
                entity_id=expense.id,
                from_state_id=None if from_state is None else from_state.id,
                to_state_id=to_state.id,
                transition_id=None if used is None else used.id,
                performed_by_user_id=actor.id,
                comments=comment,
            )
        )
    return len(steps)


def seed_all(db: Session) -> dict[str, int]:
    """
    Bring the metadata in the database in line with the definitions above,
    and return a summary of what changed. Safe to run repeatedly.
    """
    changed = {"roles": 0, "permissions": 0, "applications": 0, "renamed": 0,
               "screens": 0, "screens_removed": 0, "links": 0, "admin_roles": 0,
               "business_unit_types": 0, "business_units": 0,
               "user_business_units": 0, "dashboards": 0, "widgets": 0,
               "workflows": 0, "workflow_states": 0,
               "workflow_transitions": 0, "employees": 0,
               "widgets_removed": 0, "leave_types": 0, "leave_requests": 0,
               "leave_history": 0, "attendance": 0, "timesheets": 0,
               "timesheet_history": 0, "expense_categories": 0, "expenses": 0,
               "expense_history": 0}

    # --- applications that were renamed ------------------------------------
    # Done first, so the rest of the seed finds the row under its new code
    # rather than creating a duplicate. Renaming keeps the id, and with it
    # every role_applications and screens row that points at it.
    for old_code, new_code in RENAMED_APPLICATIONS.items():
        legacy = db.scalar(select(Application).where(Application.code == old_code))
        if legacy is not None:
            legacy.code = new_code
            changed["renamed"] += 1
    db.flush()

    # --- screens that were renamed -----------------------------------------
    for old_code, new_code in RENAMED_SCREENS.items():
        for legacy in db.scalars(select(Screen).where(Screen.code == old_code)):
            legacy.code = new_code
            changed["renamed"] += 1
    db.flush()

    # --- roles -------------------------------------------------------------
    roles: dict[str, Role] = {}
    for seed in ROLES:
        role = db.scalar(select(Role).where(Role.code == seed.code))
        if role is None:
            role = Role(code=seed.code, name=seed.name,
                        description=seed.description, is_system_role=True)
            db.add(role)
            changed["roles"] += 1
        elif role.name != seed.name or role.description != seed.description:
            role.name, role.description = seed.name, seed.description
            changed["roles"] += 1
        roles[seed.code] = role

    # --- permissions -------------------------------------------------------
    permissions: dict[str, Permission] = {}
    for seed in PERMISSIONS:
        permission = db.scalar(select(Permission).where(Permission.code == seed.code))
        if permission is None:
            permission = Permission(code=seed.code, name=seed.name,
                                    description=seed.description)
            db.add(permission)
            changed["permissions"] += 1
        permissions[seed.code] = permission

    # --- applications ------------------------------------------------------
    applications: dict[str, Application] = {}
    for seed in APPLICATIONS:
        application = db.scalar(
            select(Application).where(Application.code == seed.code)
        )
        if application is None:
            application = Application(code=seed.code, display_order=seed.display_order)
            db.add(application)
            changed["applications"] += 1
        elif (application.name != seed.name
              or application.description != seed.description
              or application.is_platform_admin_app != seed.is_platform_admin_app):
            changed["applications"] += 1

        # Descriptive fields are always brought in line, so correcting a name
        # here is enough to correct it in the database.
        application.name = seed.name
        application.description = seed.description
        application.icon = seed.icon
        application.route = f"/apps/{seed.code.lower()}"
        application.is_platform_admin_app = seed.is_platform_admin_app
        application.display_order = seed.display_order
        applications[seed.code] = application

    db.flush()

    # --- screens -----------------------------------------------------------
    screens: dict[str, Screen] = {}
    for seed in SCREENS:
        application = applications[seed.application_code]
        screen = db.scalar(
            select(Screen).where(
                Screen.application_id == application.id, Screen.code == seed.code
            )
        )
        if screen is None:
            screen = Screen(application_id=application.id, code=seed.code)
            db.add(screen)
            changed["screens"] += 1
        elif screen.name != seed.name:
            changed["screens"] += 1

        screen.name = seed.name
        screen.route = f"/apps/{seed.application_code.lower()}/{seed.code.lower()}"
        screen.display_order = seed.display_order
        screens[seed.code] = screen

    db.flush()

    # --- screens that no longer belong -------------------------------------
    # Any screen of a seeded application that is not in SCREENS is obsolete -
    # this is what removes the old Course List and My Learning rows. Deleting
    # a screen also deletes its role_screens links, through ON DELETE CASCADE.
    wanted_by_application: dict[int, set[str]] = {}
    for seed in SCREENS:
        wanted_by_application.setdefault(
            applications[seed.application_code].id, set()
        ).add(seed.code)

    for application in applications.values():
        wanted_codes = wanted_by_application.get(application.id, set())
        for screen in db.scalars(
            select(Screen).where(Screen.application_id == application.id)
        ):
            if screen.code not in wanted_codes:
                db.delete(screen)
                changed["screens_removed"] += 1

    db.flush()

    # --- role -> permission ------------------------------------------------
    for role_code, wanted in ROLE_PERMISSIONS.items():
        codes = list(permissions) if wanted == ALL else wanted
        changed["links"] += _reconcile(
            roles[role_code].permissions, [permissions[c] for c in codes]
        )

    # --- role -> application -----------------------------------------------
    for role_code, wanted in ROLE_APPLICATIONS.items():
        codes = list(applications) if wanted == ALL else wanted
        changed["links"] += _reconcile(
            roles[role_code].applications, [applications[c] for c in codes]
        )

    # --- role -> screen ----------------------------------------------------
    # Every screen of every application the role can open, minus exclusions.
    for role_code, wanted in ROLE_APPLICATIONS.items():
        app_codes = list(applications) if wanted == ALL else wanted
        excluded = ROLE_SCREEN_EXCLUSIONS.get(role_code, [])
        wanted_screens = [
            screens[seed.code]
            for seed in SCREENS
            if seed.application_code in app_codes and seed.code not in excluded
        ]
        changed["links"] += _reconcile(roles[role_code].screens, wanted_screens)

    # --- dashboards --------------------------------------------------------
    dashboards: dict[str, Dashboard] = {}
    for seed in DASHBOARDS:
        screen = screens[seed.screen_code]
        dashboard = db.scalar(
            select(Dashboard).where(
                Dashboard.screen_id == screen.id, Dashboard.code == seed.code
            )
        )
        if dashboard is None:
            dashboard = Dashboard(screen_id=screen.id, code=seed.code)
            db.add(dashboard)
            changed["dashboards"] += 1
        elif dashboard.name != seed.name:
            changed["dashboards"] += 1
        dashboard.name = seed.name
        dashboard.description = seed.description
        dashboard.display_order = seed.display_order
        dashboards[seed.code] = dashboard

    db.flush()

    # --- dashboard widgets -------------------------------------------------
    # config_json is rewritten every run, so editing a sample value above and
    # re-running the seed is enough to change what the dashboard shows.
    for seed in WIDGETS:
        dashboard = dashboards[seed.dashboard_code]
        widget = db.scalar(
            select(DashboardWidget).where(
                DashboardWidget.dashboard_id == dashboard.id,
                DashboardWidget.code == seed.code,
            )
        )
        if widget is None:
            widget = DashboardWidget(dashboard_id=dashboard.id, code=seed.code)
            db.add(widget)
            changed["widgets"] += 1
        elif widget.config_json != seed.config or widget.title != seed.title:
            changed["widgets"] += 1
        widget.title = seed.title
        widget.widget_type = seed.widget_type
        widget.config_json = seed.config
        widget.width = seed.width
        widget.display_order = seed.display_order

    db.flush()

    # --- widgets that no longer belong -------------------------------------
    # The employee dashboard replaced its sample widgets with data-driven ones,
    # so the old codes have to go rather than linger beside the new tiles.
    for dashboard in dashboards.values():
        wanted_codes = {
            seed.code for seed in WIDGETS if seed.dashboard_code == dashboard.code
        }
        for widget in db.scalars(
            select(DashboardWidget).where(
                DashboardWidget.dashboard_id == dashboard.id
            )
        ):
            if widget.code not in wanted_codes:
                db.delete(widget)
                changed["widgets_removed"] += 1

    db.flush()

    # --- workflows ---------------------------------------------------------
    workflows: dict[str, Workflow] = {}
    for seed in WORKFLOWS:
        workflow = db.scalar(select(Workflow).where(Workflow.code == seed.code))
        if workflow is None:
            workflow = Workflow(code=seed.code)
            db.add(workflow)
            changed["workflows"] += 1
        workflow.name = seed.name
        workflow.description = seed.description
        workflow.application_id = (
            None if seed.application_code is None
            else applications[seed.application_code].id
        )
        workflows[seed.code] = workflow

    db.flush()

    # --- workflow states ---------------------------------------------------
    workflow_states: dict[tuple[str, str], WorkflowState] = {}
    for seed in WORKFLOW_STATES:
        workflow = workflows[seed.workflow_code]
        state = db.scalar(
            select(WorkflowState).where(
                WorkflowState.workflow_id == workflow.id,
                WorkflowState.code == seed.code,
            )
        )
        if state is None:
            state = WorkflowState(workflow_id=workflow.id, code=seed.code)
            db.add(state)
            changed["workflow_states"] += 1
        state.name = seed.name
        state.is_initial = seed.is_initial
        state.is_final = seed.is_final
        state.is_owner_held = seed.is_owner_held
        state.display_order = seed.display_order
        workflow_states[(seed.workflow_code, seed.code)] = state

    db.flush()

    # --- workflow transitions and who may perform them ---------------------
    # Kept in a dict as well, because the seeded leave requests below need the
    # transition rows to write a believable history for each fixture.
    workflow_transitions: dict[tuple[str, str], WorkflowTransition] = {}
    for seed in WORKFLOW_TRANSITIONS:
        workflow = workflows[seed.workflow_code]
        transition = db.scalar(
            select(WorkflowTransition).where(
                WorkflowTransition.workflow_id == workflow.id,
                WorkflowTransition.code == seed.code,
            )
        )
        if transition is None:
            transition = WorkflowTransition(workflow_id=workflow.id, code=seed.code)
            db.add(transition)
            changed["workflow_transitions"] += 1
        transition.name = seed.name
        transition.actor = seed.actor
        transition.from_state_id = workflow_states[
            (seed.workflow_code, seed.from_state_code)
        ].id
        transition.to_state_id = workflow_states[
            (seed.workflow_code, seed.to_state_code)
        ].id
        db.flush()

        # Reconciled, like every other role link: the seed is authoritative.
        changed["links"] += _reconcile(
            transition.allowed_roles, [roles[code] for code in seed.role_codes]
        )
        workflow_transitions[(seed.workflow_code, seed.code)] = transition

    db.flush()

    # --- business unit types -----------------------------------------------
    unit_types: dict[str, BusinessUnitType] = {}
    for seed in BUSINESS_UNIT_TYPES:
        unit_type = db.scalar(
            select(BusinessUnitType).where(BusinessUnitType.code == seed.code)
        )
        if unit_type is None:
            unit_type = BusinessUnitType(code=seed.code)
            db.add(unit_type)
            changed["business_unit_types"] += 1
        unit_type.name = seed.name
        unit_type.description = seed.description
        unit_type.display_order = seed.display_order
        unit_types[seed.code] = unit_type

    db.flush()

    # --- business units ----------------------------------------------------
    # BUSINESS_UNITS is ordered parents-first, so by the time a child is
    # created its parent already has an id.
    units: dict[str, BusinessUnit] = {}
    for seed in BUSINESS_UNITS:
        unit = db.scalar(select(BusinessUnit).where(BusinessUnit.code == seed.code))
        if unit is None:
            unit = BusinessUnit(code=seed.code)
            db.add(unit)
            changed["business_units"] += 1
        unit.name = seed.name
        unit.business_unit_type_id = unit_types[seed.type_code].id
        # A root has parent_id = None; everything else points at its parent.
        unit.parent_id = (
            None if seed.parent_code is None else units[seed.parent_code].id
        )
        units[seed.code] = unit
        db.flush()

    # --- development user -> business unit assignments ---------------------
    for username, unit_codes in DEV_USER_BUSINESS_UNITS.items():
        person = db.scalar(select(User).where(User.username == username))
        if person is None:
            continue
        for code in unit_codes:
            if units[code] not in person.business_units:
                person.business_units.append(units[code])
                changed["user_business_units"] += 1

    # --- employees ---------------------------------------------------------
    # Ordered managers-first, so manager_code always resolves to a record that
    # already exists.
    employees: dict[str, Employee] = {}
    for seed in EMPLOYEES:
        employee = db.scalar(
            select(Employee).where(Employee.employee_code == seed.code)
        )
        if employee is None:
            employee = Employee(employee_code=seed.code)
            db.add(employee)
            changed["employees"] += 1

        employee.first_name = seed.first_name
        employee.last_name = seed.last_name
        employee.email = (
            f"{seed.first_name}.{seed.last_name}@example.local".lower()
        )
        employee.job_title = seed.job_title
        employee.business_unit_id = units[seed.business_unit_code].id
        employee.employment_status = seed.status
        employee.manager_id = (
            None if seed.manager_code is None else employees[seed.manager_code].id
        )

        # Link to a development login where one exists. No password is
        # touched here - the account already exists or it does not.
        if seed.username:
            account = db.scalar(select(User).where(User.username == seed.username))
            employee.user_id = account.id if account else None

        db.flush()
        employees[seed.code] = employee

    # --- leave types -------------------------------------------------------
    leave_types: dict[str, LeaveType] = {}
    for seed in LEAVE_TYPES:
        leave_type = db.scalar(select(LeaveType).where(LeaveType.code == seed.code))
        if leave_type is None:
            leave_type = LeaveType(code=seed.code)
            db.add(leave_type)
            changed["leave_types"] += 1
        leave_type.name = seed.name
        leave_type.description = seed.description
        leave_type.max_days = seed.max_days
        leave_type.is_active = True
        leave_types[seed.code] = leave_type

    db.flush()

    # --- leave requests ----------------------------------------------------
    #
    # These are fixtures, not user data, so they are matched on the natural key
    # (employee, leave type, start date) rather than on a code column. Running
    # the seed twice updates the same 25 rows instead of creating 50.
    #
    # `total_days` is calculated here by the very same function the API calls,
    # so a seeded request can never disagree with one a person creates.
    leave_workflow = workflows["LEAVE_APPROVAL"]
    for seed in LEAVE_REQUESTS:
        employee = employees[seed.employee_code]
        leave_type = leave_types[seed.leave_type_code]
        start = date.fromisoformat(seed.start_date)
        end = date.fromisoformat(seed.end_date)

        request = db.scalar(
            select(LeaveRequest).where(
                LeaveRequest.employee_id == employee.id,
                LeaveRequest.leave_type_id == leave_type.id,
                LeaveRequest.start_date == start,
            )
        )
        if request is None:
            request = LeaveRequest(
                employee_id=employee.id,
                leave_type_id=leave_type.id,
                start_date=start,
            )
            db.add(request)
            changed["leave_requests"] += 1

        request.end_date = end
        request.total_days = leave_service.calculate_total_days(start, end)
        request.reason = seed.reason
        request.workflow_id = leave_workflow.id
        request.current_state_id = workflow_states[
            ("LEAVE_APPROVAL", seed.state_code)
        ].id
        db.flush()

        changed["leave_history"] += _seed_leave_history(
            db, request, seed, employees, workflow_states, workflow_transitions
        )

    db.flush()

    # --- attendance --------------------------------------------------------
    #
    # Generated rather than listed: 20 people times three weeks is 400-odd
    # rows, and a literal list that long would bury the definitions above
    # without teaching anything. The generator is deterministic, so this stays
    # idempotent - the same day always produces the same record.
    #
    # `worked_minutes` and the status are NOT taken from the fixture. They are
    # computed by the very same functions the check-out endpoint calls, so
    # seeded data can never disagree with data a person creates.
    current_day = attendance_service.today()
    for seed in build_attendance_rows(current_day):
        employee = employees[seed.employee_code]

        record = db.scalar(
            select(Attendance).where(
                Attendance.employee_id == employee.id,
                Attendance.attendance_date == seed.attendance_date,
            )
        )
        if record is None:
            record = Attendance(
                employee_id=employee.id,
                attendance_date=seed.attendance_date,
            )
            db.add(record)
            changed["attendance"] += 1

        record.check_in = seed.check_in
        record.check_out = seed.check_out
        record.worked_minutes = attendance_service.calculate_worked_minutes(
            seed.check_in, seed.check_out
        )
        record.attendance_status = seed.status_override or attendance_service.derive_status(
            seed.check_in, seed.check_out, record.worked_minutes
        )
        record.remarks = seed.remarks

    db.flush()

    # --- timesheets --------------------------------------------------------
    # Matched on (employee, work date), which is a natural key for the fixture
    # because it writes at most one entry per person per day. The table itself
    # allows many - a real day is several pieces of work.
    timesheet_workflow = workflows["TIMESHEET_APPROVAL"]
    for seed in build_timesheet_rows(current_day):
        employee = employees[seed.employee_code]

        entry = db.scalar(
            select(Timesheet).where(
                Timesheet.employee_id == employee.id,
                Timesheet.work_date == seed.work_date,
            )
        )
        if entry is None:
            entry = Timesheet(
                employee_id=employee.id,
                work_date=seed.work_date,
            )
            db.add(entry)
            changed["timesheets"] += 1

        entry.minutes = seed.minutes
        entry.work_description = seed.work_description
        entry.reference = seed.reference
        entry.workflow_id = timesheet_workflow.id
        entry.current_state_id = workflow_states[
            ("TIMESHEET_APPROVAL", seed.state_code)
        ].id
        db.flush()

        changed["timesheet_history"] += _seed_timesheet_history(
            db, entry, seed, employees, workflow_states, workflow_transitions
        )

    db.flush()

    # --- expense categories ------------------------------------------------
    expense_categories: dict[str, ExpenseCategory] = {}
    for seed in EXPENSE_CATEGORIES:
        category = db.scalar(
            select(ExpenseCategory).where(ExpenseCategory.code == seed.code)
        )
        if category is None:
            category = ExpenseCategory(code=seed.code)
            db.add(category)
            changed["expense_categories"] += 1
        category.name = seed.name
        category.description = seed.description
        category.display_order = seed.display_order
        category.is_active = True
        expense_categories[seed.code] = category

    db.flush()

    # --- expenses ----------------------------------------------------------
    #
    # Generated, like the attendance and timesheet fixtures, and matched on
    # (employee, date, category) - which the generator writes at most once, so
    # it is a natural key here even though the table allows repeats.
    #
    # The amount is built from a decimal string, never a float. Money is the
    # one place where the type matters more than the convenience.
    expense_workflow = workflows["EXPENSE_APPROVAL"]
    for seed in build_expense_rows(current_day):
        employee = employees[seed.employee_code]
        category = expense_categories[seed.category_code]

        expense = db.scalar(
            select(Expense).where(
                Expense.employee_id == employee.id,
                Expense.expense_date == seed.expense_date,
                Expense.category_id == category.id,
            )
        )
        if expense is None:
            expense = Expense(
                employee_id=employee.id,
                expense_date=seed.expense_date,
                category_id=category.id,
            )
            db.add(expense)
            changed["expenses"] += 1

        expense.amount = Decimal(seed.amount)
        expense.currency = EXPENSE_CURRENCY
        expense.merchant = seed.merchant
        expense.description = seed.description
        expense.reference_number = seed.reference_number
        expense.workflow_id = expense_workflow.id
        expense.current_state_id = workflow_states[
            ("EXPENSE_APPROVAL", seed.state_code)
        ].id
        db.flush()

        changed["expense_history"] += _seed_expense_history(
            db, expense, seed, employees, workflow_states, workflow_transitions
        )

    db.flush()

    # --- the local admin user becomes SUPER_ADMIN --------------------------
    # Only ever adds: a person's own roles are not the seed's business.
    admin = db.scalar(select(User).where(User.username == ADMIN_USERNAME))
    if admin is not None:
        for role_code in ADMIN_ROLES:
            if roles[role_code] not in admin.roles:
                admin.roles.append(roles[role_code])
                changed["admin_roles"] += 1

    db.commit()
    return changed
