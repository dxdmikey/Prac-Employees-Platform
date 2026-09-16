"""
Tests for the metadata chain: Application -> Screen -> Dashboard -> Widget.

The point of these is that navigation is *data*. Nothing in the frontend
decides what a user sees, so these tests describe what the API hands it.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.metadata.seed import seed_all
from app.models.application import Application
from app.models.dashboard import Dashboard
from app.models.dashboard_widget import DashboardWidget
from app.models.screen import Screen

WIDGET_TYPES = {"stat", "bar", "line", "pie", "table"}


def get(client: TestClient, login_headers, username: str, path: str):
    return client.get(path, headers=login_headers(username))


# --- 1-3. the launcher's data ----------------------------------------------


def test_authorized_user_receives_their_accessible_applications(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("hr_person", ("HR",))

    body = get(client, login_headers, "hr_person", "/api/access/me").json()

    assert {a["code"] for a in body["applications"]} == {
        "EMPLOYEE_MANAGEMENT", "LEAVE_MANAGEMENT", "PAYROLL",
        "ATTENDANCE_TIMESHEET", "EXPENSE_MANAGEMENT",
    }
    # The metadata the launcher renders with is all present.
    for application in body["applications"]:
        assert application["name"] and application["route"]
        assert application["display_order"] >= 0


def test_platform_admin_applications_are_excluded_for_business_roles(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("worker", ("EMPLOYEE",))

    body = get(client, login_headers, "worker", "/api/access/me").json()
    codes = {a["code"] for a in body["applications"]}

    assert not (codes & {"USER_MANAGEMENT", "ROLE_MANAGEMENT", "USER_ROLE_MANAGEMENT"})
    # Guessing the code directly does not help either.
    assert get(
        client, login_headers, "worker", "/api/access/applications/USER_MANAGEMENT"
    ).status_code == 404


@pytest.mark.parametrize(
    ("role_code", "expected"),
    [("SUPER_ADMIN", 8), ("HR", 5), ("MANAGER", 5), ("EMPLOYEE", 4)],
)
def test_application_count_matches_the_returned_metadata(
    client: TestClient, seeded: Session, make_user, login_headers,
    role_code: str, expected: int,
) -> None:
    """The launcher's "N of M" is derived, never typed in."""
    make_user("person", (role_code,))

    body = get(client, login_headers, "person", "/api/access/me").json()

    assert len(body["applications"]) == expected == body["applications"].__len__()
    assert body["total_applications"] == 8


# --- 4-5. screens -----------------------------------------------------------


def test_authorized_user_retrieves_the_screens_of_an_application(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("boss", ("SUPER_ADMIN",))

    response = get(
        client, login_headers, "boss", "/api/access/applications/PAYROLL/screens"
    )

    assert response.status_code == 200
    assert [s["code"] for s in response.json()] == [
        "PAYROLL_DASHBOARD", "MY_SALARY", "SALARY_COMPONENTS"
    ]


def test_unauthorized_user_cannot_retrieve_another_applications_screens(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("worker", ("EMPLOYEE",))     # no Employee Management access

    assert get(
        client, login_headers, "worker",
        "/api/access/applications/EMPLOYEE_MANAGEMENT/screens",
    ).status_code == 403

    # Nor a single screen from inside it, by code.
    assert get(
        client, login_headers, "worker", "/api/access/screens/EMPLOYEE_LIST"
    ).status_code == 404


def test_screen_navigation_differs_by_role(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """Same application, different navigation - decided entirely by metadata."""
    make_user("worker", ("EMPLOYEE",))
    make_user("hr_person", ("HR",))

    def payroll_screens(username: str) -> list[str]:
        return [
            s["code"]
            for s in get(
                client, login_headers, username,
                "/api/access/applications/PAYROLL/screens",
            ).json()
        ]

    assert payroll_screens("worker") == ["MY_SALARY"]
    assert payroll_screens("hr_person") == [
        "PAYROLL_DASHBOARD", "MY_SALARY", "SALARY_COMPONENTS"
    ]


# --- 6-8. dashboards and widgets -------------------------------------------


def test_dashboard_belongs_to_the_correct_screen(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    make_user("boss", ("SUPER_ADMIN",))
    screen = db.scalar(select(Screen).where(Screen.code == "PAYROLL_DASHBOARD"))

    dashboards = get(
        client, login_headers, "boss",
        "/api/access/screens/PAYROLL_DASHBOARD/dashboards",
    ).json()

    assert {d["code"] for d in dashboards} == {"PAYROLL_SUMMARY", "SALARY_BREAKDOWN"}
    for dashboard in dashboards:
        assert dashboard["screen_id"] == screen.id


def test_widgets_belong_to_the_correct_dashboard(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    make_user("boss", ("SUPER_ADMIN",))
    dashboard = db.scalar(
        select(Dashboard).where(Dashboard.code == "PAYROLL_SUMMARY")
    )

    widgets = get(
        client, login_headers, "boss",
        "/api/access/dashboards/PAYROLL_SUMMARY/widgets",
    ).json()

    assert len(widgets) == 4
    for widget in widgets:
        assert widget["dashboard_id"] == dashboard.id

    # And the same widgets arrive with the screen, so one request is enough.
    dashboards = get(
        client, login_headers, "boss",
        "/api/access/screens/PAYROLL_DASHBOARD/dashboards",
    ).json()
    summary = next(d for d in dashboards if d["code"] == "PAYROLL_SUMMARY")
    assert [w["code"] for w in summary["widgets"]] == [w["code"] for w in widgets]


def test_widget_metadata_is_complete_and_renderable(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """Every widget must carry what the frontend needs to draw it."""
    make_user("boss", ("SUPER_ADMIN",))

    widgets = get(
        client, login_headers, "boss",
        "/api/access/dashboards/PAYROLL_SUMMARY/widgets",
    ).json()

    for widget in widgets:
        assert widget["widget_type"] in WIDGET_TYPES
        assert widget["title"]
        assert widget["config_json"] is not None
        assert 1 <= widget["width"] <= 12

    stat = next(w for w in widgets if w["widget_type"] == "stat")
    assert isinstance(stat["config_json"]["value"], (int, float))

    line = next(w for w in widgets if w["widget_type"] == "line")
    assert line["config_json"]["categories"]
    assert line["config_json"]["series"][0]["data"]


def test_a_dashboard_cannot_be_reached_through_an_inaccessible_screen(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """Guessing a dashboard code is not a way around screen access."""
    make_user("worker", ("EMPLOYEE",))     # no PAYROLL_DASHBOARD screen

    assert get(
        client, login_headers, "worker",
        "/api/access/dashboards/PAYROLL_SUMMARY/widgets",
    ).status_code == 404
    assert get(
        client, login_headers, "worker",
        "/api/access/screens/PAYROLL_DASHBOARD/dashboards",
    ).status_code == 404


def test_metadata_endpoints_require_authentication(
    client: TestClient, seeded: Session
) -> None:
    for path in (
        "/api/access/applications/PAYROLL",
        "/api/access/screens/MY_SALARY",
        "/api/access/screens/MY_SALARY/dashboards",
        "/api/access/dashboards/PAYROLL_SUMMARY/widgets",
    ):
        assert client.get(path).status_code == 401, path


# --- 9. different users, different metadata ---------------------------------


def test_different_users_receive_different_metadata(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("boss", ("SUPER_ADMIN",))
    make_user("worker", ("EMPLOYEE",))

    boss = get(client, login_headers, "boss", "/api/access/me").json()
    worker = get(client, login_headers, "worker", "/api/access/me").json()

    assert len(boss["applications"]) == 8
    assert len(worker["applications"]) == 4
    assert {a["code"] for a in worker["applications"]} < {
        a["code"] for a in boss["applications"]
    }


# --- 12-13. the metadata itself ---------------------------------------------


def test_there_are_exactly_eight_applications_with_unique_codes(
    seeded: Session
) -> None:
    applications = list(seeded.scalars(select(Application)))

    assert len(applications) == 8
    codes = [a.code for a in applications]
    assert len(set(codes)) == 8                       # unique
    assert set(codes) == {
        "EMPLOYEE_MANAGEMENT", "LEAVE_MANAGEMENT", "PAYROLL",
        "ATTENDANCE_TIMESHEET", "EXPENSE_MANAGEMENT",
        "USER_MANAGEMENT", "ROLE_MANAGEMENT", "USER_ROLE_MANAGEMENT",
    }

    # No learning-management terminology survives anywhere in the metadata.
    haystack = " ".join(
        f"{a.name} {a.code} {a.description or ''}" for a in applications
    ).lower()
    assert "course" not in haystack and "learning" not in haystack


def test_screen_codes_are_unique_within_an_application(seeded: Session) -> None:
    duplicates = seeded.execute(
        select(Screen.application_id, Screen.code, func.count())
        .group_by(Screen.application_id, Screen.code)
        .having(func.count() > 1)
    ).all()
    assert duplicates == []


def test_every_application_has_at_least_one_screen(seeded: Session) -> None:
    for application in seeded.scalars(select(Application)):
        screens = seeded.scalars(
            select(Screen).where(Screen.application_id == application.id)
        ).all()
        assert screens, f"{application.code} has no screens"


def test_the_expected_screens_exist(seeded: Session) -> None:
    """The set named in the stage brief, exactly."""
    expected = {
        "EMPLOYEE_MANAGEMENT": {"EMPLOYEE_DASHBOARD", "EMPLOYEE_LIST", "EMPLOYEE_PROFILE"},
        "LEAVE_MANAGEMENT": {"LEAVE_DASHBOARD", "MY_LEAVE", "LEAVE_REQUESTS",
                             "LEAVE_APPROVAL"},
        "PAYROLL": {"PAYROLL_DASHBOARD", "MY_SALARY", "SALARY_COMPONENTS"},
        # Stage 10 added the two management screens, alongside the
        # self-service pair an employee sees.
        "ATTENDANCE_TIMESHEET": {"ATTENDANCE_DASHBOARD", "MY_ATTENDANCE",
                                 "TIMESHEET", "TEAM_ATTENDANCE",
                                 "TIMESHEET_APPROVAL"},
        "EXPENSE_MANAGEMENT": {"EXPENSE_DASHBOARD", "MY_EXPENSES", "EXPENSE_APPROVAL"},
        "USER_MANAGEMENT": {"USER_LIST"},
        "ROLE_MANAGEMENT": {"ROLE_LIST"},
        "USER_ROLE_MANAGEMENT": {"USER_ROLE_ASSIGNMENT"},
    }

    for application in seeded.scalars(select(Application)):
        codes = {
            s.code
            for s in seeded.scalars(
                select(Screen).where(Screen.application_id == application.id)
            )
        }
        assert codes == expected[application.code], application.code


def test_every_widget_has_a_type_the_frontend_can_render(seeded: Session) -> None:
    widgets = list(seeded.scalars(select(DashboardWidget)))

    assert widgets, "the seed should create widgets"
    for widget in widgets:
        assert widget.widget_type in WIDGET_TYPES
        assert widget.config_json is not None


def test_seed_is_idempotent(seeded: Session) -> None:
    """Running it again must change nothing."""
    before = {
        "applications": seeded.scalar(select(func.count()).select_from(Application)),
        "screens": seeded.scalar(select(func.count()).select_from(Screen)),
        "dashboards": seeded.scalar(select(func.count()).select_from(Dashboard)),
        "widgets": seeded.scalar(select(func.count()).select_from(DashboardWidget)),
    }

    changed = seed_all(seeded)
    assert all(count == 0 for count in changed.values()), changed

    after = {
        "applications": seeded.scalar(select(func.count()).select_from(Application)),
        "screens": seeded.scalar(select(func.count()).select_from(Screen)),
        "dashboards": seeded.scalar(select(func.count()).select_from(Dashboard)),
        "widgets": seeded.scalar(select(func.count()).select_from(DashboardWidget)),
    }
    assert before == after
