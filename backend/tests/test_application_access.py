"""
Tests for the corrected application metadata and role -> application access.

These lock down the rules that were wrong before: LMS means Leave Management
System, Employee Management is not self-service, Payroll is, and only a Super
Admin gets the three platform-admin applications.

Each case is written as data rather than as a separate function, so the whole
access matrix is visible in one place and a change to it is a one-line edit.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

BUSINESS_APPS = {
    "EMPLOYEE_MANAGEMENT",
    "LEAVE_MANAGEMENT",
    "PAYROLL",
    "ATTENDANCE_TIMESHEET",
    "EXPENSE_MANAGEMENT",
}
PLATFORM_ADMIN_APPS = {"USER_MANAGEMENT", "ROLE_MANAGEMENT", "USER_ROLE_MANAGEMENT"}
ALL_APPS = BUSINESS_APPS | PLATFORM_ADMIN_APPS

# The intended access matrix, exactly as specified.
EXPECTED_ACCESS: dict[str, set[str]] = {
    "SUPER_ADMIN": ALL_APPS,
    "HR": BUSINESS_APPS,
    "MANAGER": BUSINESS_APPS,
    "EMPLOYEE": BUSINESS_APPS - {"EMPLOYEE_MANAGEMENT"},
}


def access_for(client: TestClient, login_headers, username: str) -> dict:
    response = client.get("/api/access/me", headers=login_headers(username))
    assert response.status_code == 200, response.text
    return response.json()


def app_codes(body: dict) -> set[str]:
    return {a["code"] for a in body["applications"]}


# --- 1-4. how many applications each role gets ------------------------------


@pytest.mark.parametrize(
    ("role_code", "expected_count"),
    [("SUPER_ADMIN", 8), ("HR", 5), ("MANAGER", 5), ("EMPLOYEE", 4)],
)
def test_role_receives_the_expected_number_of_applications(
    client: TestClient, seeded: Session, make_user, login_headers,
    role_code: str, expected_count: int,
) -> None:
    make_user("person", (role_code,))

    body = access_for(client, login_headers, "person")

    assert len(body["applications"]) == expected_count
    assert app_codes(body) == EXPECTED_ACCESS[role_code]


# --- 5-18. the full matrix, one assertion per role/application pair ---------


@pytest.mark.parametrize("role_code", sorted(EXPECTED_ACCESS))
@pytest.mark.parametrize("application_code", sorted(ALL_APPS))
def test_application_access_matches_the_matrix(
    client: TestClient, seeded: Session, make_user, login_headers,
    role_code: str, application_code: str,
) -> None:
    """
    Covers every required case at once, including:
      Employee Management - yes for SUPER_ADMIN / HR / MANAGER, no for EMPLOYEE
      Payroll             - yes for all four, employees included
      Leave Management    - yes for all four
      the three admin apps - SUPER_ADMIN only
    """
    make_user("person", (role_code,))
    should_have = application_code in EXPECTED_ACCESS[role_code]

    body = access_for(client, login_headers, "person")
    assert (application_code in app_codes(body)) is should_have

    # The menu and the API must agree - hiding a card is not access control.
    screens = client.get(
        f"/api/access/applications/{application_code}/screens",
        headers=login_headers("person"),
    )
    assert screens.status_code == (200 if should_have else 403)


# --- 19-20. platform-admin applications stay restricted ---------------------


@pytest.mark.parametrize("role_code", ["HR", "MANAGER", "EMPLOYEE"])
def test_business_roles_never_receive_platform_admin_applications(
    client: TestClient, seeded: Session, make_user, login_headers, role_code: str
) -> None:
    make_user("person", (role_code,))
    headers = login_headers("person")

    assert not (app_codes(access_for(client, login_headers, "person"))
                & PLATFORM_ADMIN_APPS)

    # And the management endpoints behind them are closed.
    assert client.get("/api/users", headers=headers).status_code == 403
    assert client.get("/api/roles", headers=headers).status_code == 403
    assert client.get("/api/applications", headers=headers).status_code == 403


def test_application_admin_is_still_scoped_and_not_a_platform_admin(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """APPLICATION_ADMIN starts with no applications - it is granted them."""
    make_user("appadmin", ("APPLICATION_ADMIN",))
    headers = login_headers("appadmin")

    body = access_for(client, login_headers, "appadmin")
    assert body["applications"] == []
    assert client.get("/api/users", headers=headers).status_code == 403


def test_application_admin_gains_only_the_application_it_is_assigned(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    from sqlalchemy import select

    from app.models.application import Application
    from app.models.role import Role

    make_user("boss", ("SUPER_ADMIN",))
    make_user("appadmin", ("APPLICATION_ADMIN",))

    role = db.scalar(select(Role).where(Role.code == "APPLICATION_ADMIN"))
    employee_mgmt = db.scalar(
        select(Application).where(Application.code == "EMPLOYEE_MANAGEMENT")
    )

    client.post(
        f"/api/roles/{role.id}/applications",
        json={"application_id": employee_mgmt.id},
        headers=login_headers("boss"),
    )

    body = access_for(client, login_headers, "appadmin")
    assert app_codes(body) == {"EMPLOYEE_MANAGEMENT"}   # scoped, not everything
    assert not (app_codes(body) & PLATFORM_ADMIN_APPS)


# --- 21. no learning-management terminology survives ------------------------


def test_leave_management_replaced_learning_management(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("boss", ("SUPER_ADMIN",))
    headers = login_headers("boss")

    body = access_for(client, login_headers, "boss")
    leave = next(a for a in body["applications"] if a["code"] == "LEAVE_MANAGEMENT")
    assert leave["name"] == "Leave Management System"

    # The old code is gone entirely.
    assert "LMS" not in app_codes(body)

    screens = client.get(
        "/api/access/applications/LEAVE_MANAGEMENT/screens", headers=headers
    ).json()
    assert {s["code"] for s in screens} == {
        "LEAVE_DASHBOARD", "MY_LEAVE", "LEAVE_REQUESTS", "LEAVE_APPROVAL"
    }

    # Nothing anywhere in the application or its screens mentions learning.
    haystack = " ".join(
        [leave["name"], leave["description"] or ""]
        + [f"{s['name']} {s['code']} {s['route'] or ''}" for s in screens]
    ).lower()
    for banned in ("course", "learning", "enrol", "enroll"):
        assert banned not in haystack


def test_no_application_or_screen_mentions_learning(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """A sweep across every application a Super Admin can see."""
    make_user("boss", ("SUPER_ADMIN",))
    headers = login_headers("boss")
    body = access_for(client, login_headers, "boss")

    for application in body["applications"]:
        text = f"{application['name']} {application['description'] or ''}".lower()
        assert "course" not in text and "learning" not in text

        screens = client.get(
            f"/api/access/applications/{application['code']}/screens", headers=headers
        ).json()
        for screen in screens:
            screen_text = f"{screen['name']} {screen['code']}".lower()
            assert "course" not in screen_text and "learning" not in screen_text


# --- 22. the count is derived, not hardcoded --------------------------------


def test_total_application_count_is_dynamic(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    """
    total_applications is what the UI uses as the denominator in "5 of 8".
    It must be counted from the database, so deactivating an application
    changes it.
    """
    from sqlalchemy import select

    from app.models.application import Application

    make_user("person", ("EMPLOYEE",))

    body = access_for(client, login_headers, "person")
    assert body["total_applications"] == 8
    assert len(body["applications"]) == 4

    # Deactivate one application; the denominator must follow.
    payroll = db.scalar(select(Application).where(Application.code == "PAYROLL"))
    payroll.is_active = False
    db.commit()

    body = access_for(client, login_headers, "person")
    assert body["total_applications"] == 7
    assert len(body["applications"]) == 3
    assert "PAYROLL" not in app_codes(body)


def test_payroll_is_employee_facing(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """
    Every role can open Payroll - an employee needs to see their own salary.
    Opening the application is not the same as seeing everyone's data; the
    employee gets the My Salary screen but not the administration screens.
    """
    for role_code in ("SUPER_ADMIN", "HR", "MANAGER", "EMPLOYEE"):
        make_user(f"user_{role_code.lower()}", (role_code,))
        assert "PAYROLL" in app_codes(
            access_for(client, login_headers, f"user_{role_code.lower()}")
        )

    def payroll_screens(username: str) -> set[str]:
        return {
            s["code"]
            for s in client.get(
                "/api/access/applications/PAYROLL/screens",
                headers=login_headers(username),
            ).json()
        }

    assert payroll_screens("user_employee") == {"MY_SALARY"}
    assert payroll_screens("user_manager") == {"MY_SALARY"}
    assert payroll_screens("user_hr") == {
        "PAYROLL_DASHBOARD", "MY_SALARY", "SALARY_COMPONENTS"
    }


def test_employee_management_is_not_self_service(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """The correction that started this task, stated as one test."""
    make_user("worker", ("EMPLOYEE",))
    headers = login_headers("worker")

    assert "EMPLOYEE_MANAGEMENT" not in app_codes(
        access_for(client, login_headers, "worker")
    )
    assert client.get(
        "/api/access/applications/EMPLOYEE_MANAGEMENT/screens", headers=headers
    ).status_code == 403

    for role_code in ("SUPER_ADMIN", "HR", "MANAGER"):
        make_user(f"u_{role_code.lower()}", (role_code,))
        assert "EMPLOYEE_MANAGEMENT" in app_codes(
            access_for(client, login_headers, f"u_{role_code.lower()}")
        )
