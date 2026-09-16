"""
Tests for metadata-driven RBAC.

Each test builds a user with real seeded roles and then asks the API what that
user can do, so the assertions describe access rules rather than code paths.
"""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.permission import Permission
from app.models.role import Role
from app.models.screen import Screen

PLATFORM_ADMIN_APPS = {"USER_MANAGEMENT", "ROLE_MANAGEMENT", "USER_ROLE_MANAGEMENT"}


def app_codes(access_body: dict) -> set[str]:
    return {a["code"] for a in access_body["applications"]}


# --- 1. Super Admin sees everything -----------------------------------------


def test_super_admin_can_retrieve_all_applications(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("boss", ("SUPER_ADMIN",))

    body = client.get("/api/access/me", headers=login_headers("boss")).json()

    assert len(body["applications"]) == 8
    assert PLATFORM_ADMIN_APPS <= app_codes(body)


# --- 2. an ordinary role never sees the platform-admin applications ---------


def test_normal_user_cannot_retrieve_platform_admin_applications(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("worker", ("EMPLOYEE",))
    headers = login_headers("worker")

    body = client.get("/api/access/me", headers=headers).json()
    assert app_codes(body) == {
        "LEAVE_MANAGEMENT", "PAYROLL", "ATTENDANCE_TIMESHEET", "EXPENSE_MANAGEMENT"
    }
    assert not (PLATFORM_ADMIN_APPS & app_codes(body))

    # Hiding it in the menu is not enough - the API must refuse it too.
    response = client.get(
        "/api/access/applications/USER_MANAGEMENT/screens", headers=headers
    )
    assert response.status_code == 403

    # And the management endpoints themselves are closed.
    assert client.get("/api/roles", headers=headers).status_code == 403
    assert client.get("/api/users", headers=headers).status_code == 403


# --- 3. a role brings its permissions ---------------------------------------


def test_user_receives_the_permissions_of_the_assigned_role(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("hr_person", ("HR",))

    body = client.get("/api/access/me", headers=login_headers("hr_person")).json()
    codes = {p["code"] for p in body["permissions"]}

    assert codes == {"VIEW", "CREATE", "EDIT", "EXPORT", "APPROVE"}
    assert "CONFIGURE" not in codes
    assert [r["code"] for r in body["roles"]] == ["HR"]


def test_permissions_from_two_roles_are_merged_without_duplicates(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("hybrid", ("EMPLOYEE", "MANAGER"))

    body = client.get("/api/access/me", headers=login_headers("hybrid")).json()
    codes = [p["code"] for p in body["permissions"]]

    assert sorted(codes) == sorted(set(codes))          # VIEW appears once
    assert set(codes) == {"VIEW", "APPROVE", "EXPORT"}


# --- 4 & 5. permission enforcement on a protected endpoint ------------------


def test_user_without_edit_cannot_call_the_edit_protected_endpoint(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("viewer", ("EMPLOYEE",))   # EMPLOYEE holds VIEW only

    response = client.get("/api/rbac/test-edit", headers=login_headers("viewer"))

    assert response.status_code == 403
    assert "EDIT" in response.json()["detail"]


def test_user_with_edit_can_call_the_protected_endpoint(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("editor", ("HR",))         # HR holds EDIT

    response = client.get("/api/rbac/test-edit", headers=login_headers("editor"))

    assert response.status_code == 200
    assert response.json()["username"] == "editor"


def test_protected_endpoint_still_requires_authentication(
    client: TestClient, seeded: Session
) -> None:
    assert client.get("/api/rbac/test-edit").status_code == 401


# --- 6 & 7. assigning and removing roles ------------------------------------


def test_admin_can_assign_a_role_to_a_user(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    make_user("boss", ("SUPER_ADMIN",))
    target = make_user("newbie", ())
    hr_role = db.scalar(select(Role).where(Role.code == "HR"))

    response = client.post(
        f"/api/users/{target.id}/roles",
        json={"role_id": hr_role.id},
        headers=login_headers("boss"),
    )

    assert response.status_code == 201
    assert [r["code"] for r in response.json()] == ["HR"]

    # The change is real: the user's own access now reflects it.
    body = client.get("/api/access/me", headers=login_headers("newbie")).json()
    assert "PAYROLL" in app_codes(body)


def test_removing_a_role_changes_effective_access(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    target = make_user("temp_hr", ("HR",))
    make_user("boss", ("SUPER_ADMIN",))
    hr_role = db.scalar(select(Role).where(Role.code == "HR"))

    before = client.get("/api/access/me", headers=login_headers("temp_hr")).json()
    assert "PAYROLL" in app_codes(before)
    assert client.get(
        "/api/rbac/test-edit", headers=login_headers("temp_hr")
    ).status_code == 200

    response = client.delete(
        f"/api/users/{target.id}/roles/{hr_role.id}", headers=login_headers("boss")
    )
    assert response.status_code == 200
    assert response.json() == []

    # Access collapses immediately - no re-login needed.
    after = client.get("/api/access/me", headers=login_headers("temp_hr")).json()
    assert after["applications"] == []
    assert after["permissions"] == []
    assert client.get(
        "/api/rbac/test-edit", headers=login_headers("temp_hr")
    ).status_code == 403


def test_assigning_the_same_role_twice_is_harmless(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    make_user("boss", ("SUPER_ADMIN",))
    target = make_user("dupe", ("HR",))
    hr_role = db.scalar(select(Role).where(Role.code == "HR"))

    response = client.post(
        f"/api/users/{target.id}/roles",
        json={"role_id": hr_role.id},
        headers=login_headers("boss"),
    )

    assert response.status_code == 201
    assert [r["code"] for r in response.json()] == ["HR"]   # still just one


def test_non_admin_cannot_assign_roles(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    attacker = make_user("sneaky", ("EMPLOYEE",))
    admin_role = db.scalar(select(Role).where(Role.code == "SUPER_ADMIN"))

    response = client.post(
        f"/api/users/{attacker.id}/roles",
        json={"role_id": admin_role.id},
        headers=login_headers("sneaky"),
    )

    assert response.status_code == 403


# --- 8. screen filtering ----------------------------------------------------


def test_accessible_screens_are_filtered_by_role(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("worker", ("EMPLOYEE",))
    make_user("lead", ("MANAGER",))

    def expense_screens(username: str) -> set[str]:
        response = client.get(
            "/api/access/applications/EXPENSE_MANAGEMENT/screens",
            headers=login_headers(username),
        )
        assert response.status_code == 200
        return {s["code"] for s in response.json()}

    # Both can open the application, and both get their own claims...
    assert "MY_EXPENSES" in expense_screens("worker")
    assert "MY_EXPENSES" in expense_screens("lead")

    # ...but only the manager sees the approval screen and the dashboard.
    assert "EXPENSE_APPROVAL" not in expense_screens("worker")
    assert "EXPENSE_DASHBOARD" not in expense_screens("worker")
    assert "EXPENSE_APPROVAL" in expense_screens("lead")
    assert "EXPENSE_DASHBOARD" in expense_screens("lead")


def test_super_admin_sees_every_screen_of_an_application(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("boss", ("SUPER_ADMIN",))

    response = client.get(
        "/api/access/applications/EXPENSE_MANAGEMENT/screens",
        headers=login_headers("boss"),
    )

    assert {s["code"] for s in response.json()} == {
        "EXPENSE_DASHBOARD", "MY_EXPENSES", "EXPENSE_APPROVAL"
    }


# --- APPLICATION_ADMIN is not a platform admin ------------------------------


def test_application_admin_is_not_a_platform_admin(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """
    APPLICATION_ADMIN holds CONFIGURE, but management access is granted by
    application, not by permission - so it cannot administer the platform.
    """
    make_user("appadmin", ("APPLICATION_ADMIN",))
    headers = login_headers("appadmin")

    body = client.get("/api/access/me", headers=headers).json()
    assert "CONFIGURE" in {p["code"] for p in body["permissions"]}
    assert body["applications"] == []

    assert client.get("/api/users", headers=headers).status_code == 403
    assert client.get("/api/roles", headers=headers).status_code == 403


# --- deactivation ------------------------------------------------------------


def test_deactivating_a_role_removes_its_access(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    make_user("hr_person", ("HR",))
    headers = login_headers("hr_person")
    assert client.get("/api/access/me", headers=headers).json()["applications"]

    role = db.scalar(select(Role).where(Role.code == "HR"))
    role.is_active = False
    db.commit()

    body = client.get("/api/access/me", headers=headers).json()
    assert body["applications"] == []
    assert body["roles"] == []


# --- role composition management --------------------------------------------


def test_admin_can_grant_and_revoke_a_role_permission(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    make_user("boss", ("SUPER_ADMIN",))
    make_user("worker", ("EMPLOYEE",))
    admin = login_headers("boss")

    employee_role = db.scalar(select(Role).where(Role.code == "EMPLOYEE"))
    edit = db.scalar(select(Permission).where(Permission.code == "EDIT"))

    # The employee cannot use the EDIT endpoint yet.
    assert client.get(
        "/api/rbac/test-edit", headers=login_headers("worker")
    ).status_code == 403

    granted = client.post(
        f"/api/roles/{employee_role.id}/permissions",
        json={"permission_id": edit.id},
        headers=admin,
    )
    assert granted.status_code == 201
    assert "EDIT" in {p["code"] for p in granted.json()}

    # Granting a permission to the role immediately changes what the user can do.
    assert client.get(
        "/api/rbac/test-edit", headers=login_headers("worker")
    ).status_code == 200

    revoked = client.delete(
        f"/api/roles/{employee_role.id}/permissions/{edit.id}", headers=admin
    )
    assert revoked.status_code == 200
    assert "EDIT" not in {p["code"] for p in revoked.json()}
    assert client.get(
        "/api/rbac/test-edit", headers=login_headers("worker")
    ).status_code == 403


def test_admin_can_grant_and_revoke_a_role_application(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    make_user("boss", ("SUPER_ADMIN",))
    make_user("worker", ("EMPLOYEE",))
    admin = login_headers("boss")

    employee_role = db.scalar(select(Role).where(Role.code == "EMPLOYEE"))
    # Employee Management is deliberately not part of the EMPLOYEE role, which
    # makes it the right application for testing a grant.
    target = db.scalar(
        select(Application).where(Application.code == "EMPLOYEE_MANAGEMENT")
    )

    assert "EMPLOYEE_MANAGEMENT" not in app_codes(
        client.get("/api/access/me", headers=login_headers("worker")).json()
    )

    response = client.post(
        f"/api/roles/{employee_role.id}/applications",
        json={"application_id": target.id},
        headers=admin,
    )
    assert response.status_code == 201
    assert "EMPLOYEE_MANAGEMENT" in app_codes(
        client.get("/api/access/me", headers=login_headers("worker")).json()
    )

    client.delete(
        f"/api/roles/{employee_role.id}/applications/{target.id}", headers=admin
    )
    assert "EMPLOYEE_MANAGEMENT" not in app_codes(
        client.get("/api/access/me", headers=login_headers("worker")).json()
    )


def test_admin_can_grant_a_role_screen(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    make_user("boss", ("SUPER_ADMIN",))
    make_user("worker", ("EMPLOYEE",))
    admin = login_headers("boss")

    employee_role = db.scalar(select(Role).where(Role.code == "EMPLOYEE"))
    approval = db.scalar(select(Screen).where(Screen.code == "EXPENSE_APPROVAL"))

    def worker_expense_screens() -> set[str]:
        return {
            s["code"]
            for s in client.get(
                "/api/access/applications/EXPENSE_MANAGEMENT/screens",
                headers=login_headers("worker"),
            ).json()
        }

    assert "EXPENSE_APPROVAL" not in worker_expense_screens()

    response = client.post(
        f"/api/roles/{employee_role.id}/screens",
        json={"screen_id": approval.id},
        headers=admin,
    )
    assert response.status_code == 201
    assert "EXPENSE_APPROVAL" in worker_expense_screens()


def test_unknown_ids_return_404(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("boss", ("SUPER_ADMIN",))
    admin = login_headers("boss")

    assert client.get("/api/users/999999/roles", headers=admin).status_code == 404
    assert client.post(
        "/api/users/999999/roles", json={"role_id": 1}, headers=admin
    ).status_code == 404
