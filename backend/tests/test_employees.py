"""
Tests for Employee Management.

Two things are being proven here, and the second is the one that matters most:

  1. the CRUD works, and
  2. **every read is scoped**. An HR user in Company 1 must not see Company 2,
     in the list, in a single record, or in the dashboard totals.

The seeded workforce, which the scope tests rely on:

    Headquarters (22)
      Company 1 (15)
        Branch 1 (7)  -> Department 1 (3), Department 2 (3)
        Branch 2      -> Department 3 (3), Department 4 (2)
      Company 2 (6)
        Branch 3      -> Department 5 (2), Department 6 (2)
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.business_unit import BusinessUnit
from app.models.employee import Employee
from app.services import employee_service
from app.services.employee_service import EmployeeError


def unit(db: Session, code: str) -> BusinessUnit:
    return db.scalar(select(BusinessUnit).where(BusinessUnit.code == code))


def assign(db: Session, user, *codes: str):
    for code in codes:
        user.business_units.append(unit(db, code))
    db.commit()
    return user


def scoped_user(db, make_user, username: str, role: str, unit_code: str):
    """A user with a role (what) and a business unit (where)."""
    return assign(db, make_user(username, (role,)), unit_code)


def list_codes(client: TestClient, headers, **params) -> set[str]:
    response = client.get("/api/employees", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return {row["employee_code"] for row in response.json()["items"]}


# --- 1-5. the model ---------------------------------------------------------


def test_employee_can_be_created(seeded: Session, make_user) -> None:
    hr = scoped_user(seeded, make_user, "hr", "HR", "COMPANY_1")

    employee = employee_service.create_employee(
        seeded,
        hr,
        {
            "employee_code": "EMP-NEW",
            "first_name": "New",
            "last_name": "Starter",
            "email": "new.starter@example.local",
            "business_unit_id": unit(seeded, "DEPARTMENT_1").id,
            "manager_id": None,
            "employment_status": "ACTIVE",
        },
    )

    assert employee.id is not None
    assert employee.full_name == "New Starter"


def test_employee_code_must_be_unique(seeded: Session, make_user) -> None:
    hr = scoped_user(seeded, make_user, "hr", "HR", "COMPANY_1")

    with pytest.raises(EmployeeError, match="already exists"):
        employee_service.create_employee(
            seeded,
            hr,
            {
                "employee_code": "EMP-005",          # already seeded
                "first_name": "Clash",
                "last_name": "Test",
                "email": "clash@example.local",
                "business_unit_id": unit(seeded, "DEPARTMENT_1").id,
            },
        )


def test_employee_links_to_business_unit_and_manager(seeded: Session) -> None:
    employee = seeded.scalar(select(Employee).where(Employee.employee_code == "EMP-005"))

    assert employee.business_unit.code == "DEPARTMENT_1"
    assert employee.manager.employee_code == "EMP-004"
    # And the reverse direction of the self-reference works.
    assert "EMP-005" in {report.employee_code for report in employee.manager.reports}


def test_self_manager_is_rejected(seeded: Session, make_user) -> None:
    hr = scoped_user(seeded, make_user, "hr", "HR", "COMPANY_1")
    employee = seeded.scalar(select(Employee).where(Employee.employee_code == "EMP-005"))

    with pytest.raises(EmployeeError, match="own manager"):
        employee_service.update_employee(
            seeded, hr, employee, {"manager_id": employee.id}
        )


def test_invalid_business_unit_is_rejected(seeded: Session, make_user) -> None:
    hr = scoped_user(seeded, make_user, "hr", "HR", "COMPANY_1")

    with pytest.raises(EmployeeError, match="No business unit"):
        employee_service.create_employee(
            seeded,
            hr,
            {
                "employee_code": "EMP-BAD",
                "first_name": "Bad",
                "last_name": "Unit",
                "email": "bad.unit@example.local",
                "business_unit_id": 999999,
            },
        )


# --- 6-10. CRUD through the API ---------------------------------------------


def test_authorized_user_can_view_and_edit(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    scoped_user(db, make_user, "hr", "HR", "COMPANY_1")
    headers = login_headers("hr")

    employee = db.scalar(select(Employee).where(Employee.employee_code == "EMP-005"))
    read = client.get(f"/api/employees/{employee.id}", headers=headers)
    assert read.status_code == 200
    assert read.json()["employee_code"] == "EMP-005"
    # Nothing from the authentication side leaks into the response.
    assert "password_hash" not in read.text

    edited = client.put(
        f"/api/employees/{employee.id}",
        json={"job_title": "Senior Software Engineer"},
        headers=headers,
    )
    assert edited.status_code == 200
    assert edited.json()["job_title"] == "Senior Software Engineer"
    # An omitted field is left alone, not nulled.
    assert edited.json()["email"] == employee.email


def test_authorized_user_can_create(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    scoped_user(db, make_user, "hr", "HR", "COMPANY_1")

    response = client.post(
        "/api/employees",
        json={
            "employee_code": "EMP-API",
            "first_name": "Api",
            "last_name": "Created",
            "email": "api.created@example.local",
            "business_unit_id": unit(db, "DEPARTMENT_2").id,
        },
        headers=login_headers("hr"),
    )

    assert response.status_code == 201
    assert response.json()["business_unit"]["name"] == "Department 2"


def test_a_manager_cannot_create_or_edit(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    """
    MANAGER can open the application and read, but holds neither CREATE nor
    EDIT - the permission decides, not the role name.
    """
    scoped_user(db, make_user, "lead", "MANAGER", "BRANCH_1")
    headers = login_headers("lead")

    assert client.get("/api/employees", headers=headers).status_code == 200

    created = client.post(
        "/api/employees",
        json={
            "employee_code": "EMP-NOPE",
            "first_name": "No",
            "last_name": "Permission",
            "email": "no.permission@example.local",
            "business_unit_id": unit(db, "DEPARTMENT_1").id,
        },
        headers=headers,
    )
    assert created.status_code == 403
    assert "CREATE" in created.json()["detail"]

    employee = db.scalar(select(Employee).where(Employee.employee_code == "EMP-005"))
    edited = client.put(
        f"/api/employees/{employee.id}", json={"job_title": "x"}, headers=headers
    )
    assert edited.status_code == 403


def test_creating_outside_your_scope_is_rejected(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    """The critical one: an id from the frontend is a request, not a fact."""
    scoped_user(db, make_user, "hr", "HR", "COMPANY_1")

    response = client.post(
        "/api/employees",
        json={
            "employee_code": "EMP-CROSS",
            "first_name": "Cross",
            "last_name": "Boundary",
            "email": "cross.boundary@example.local",
            # Company 2 - outside this HR user's scope entirely.
            "business_unit_id": unit(db, "DEPARTMENT_5").id,
        },
        headers=login_headers("hr"),
    )

    assert response.status_code == 400
    assert "outside your organisational scope" in response.json()["detail"]


# --- 11-15. business-unit scope ---------------------------------------------


def test_hr_at_company_1_sees_its_descendants_only(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    scoped_user(db, make_user, "hr", "HR", "COMPANY_1")
    headers = login_headers("hr")

    body = client.get("/api/employees", headers=headers, params={"page_size": 100}).json()
    codes = {row["employee_code"] for row in body["items"]}

    assert body["total"] == 15
    assert "EMP-005" in codes          # Department 1, deep inside Company 1
    assert "EMP-002" in codes          # Company 1 itself
    # Nothing from Company 2, and nothing from Headquarters above them.
    assert "EMP-019" not in codes
    assert "EMP-001" not in codes


def test_hr_cannot_read_a_company_2_employee_directly(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    scoped_user(db, make_user, "hr", "HR", "COMPANY_1")
    outsider = db.scalar(select(Employee).where(Employee.employee_code == "EMP-019"))

    response = client.get(f"/api/employees/{outsider.id}", headers=login_headers("hr"))

    assert response.status_code == 403


def test_manager_at_branch_1_sees_only_that_branch(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    scoped_user(db, make_user, "lead", "MANAGER", "BRANCH_1")
    codes = list_codes(client, login_headers("lead"), page_size=100)

    assert codes == {
        "EMP-004", "EMP-005", "EMP-006", "EMP-007", "EMP-008", "EMP-009", "EMP-010"
    }
    assert "EMP-012" not in codes      # Branch 2 - a sibling, not a descendant


def test_department_scope_is_the_narrowest(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    # HR role for the application access, Department 1 for the scope.
    scoped_user(db, make_user, "dept_hr", "HR", "DEPARTMENT_1")
    codes = list_codes(client, login_headers("dept_hr"), page_size=100)

    assert codes == {"EMP-005", "EMP-006", "EMP-007"}


def test_changing_the_assignment_changes_what_is_visible(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    """Scope is data: move the assignment, and the list moves with it."""
    person = scoped_user(db, make_user, "mover", "HR", "DEPARTMENT_1")
    headers = login_headers("mover")
    assert len(list_codes(client, headers, page_size=100)) == 3

    person.business_units.clear()
    person.business_units.append(unit(db, "COMPANY_2"))
    db.commit()

    codes = list_codes(client, headers, page_size=100)
    assert len(codes) == 6
    assert "EMP-019" in codes and "EMP-005" not in codes


def test_a_user_with_no_assignment_sees_nobody(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """No assignment must mean nothing - never everything."""
    make_user("unplaced", ("HR",))

    body = client.get("/api/employees", headers=login_headers("unplaced")).json()
    assert body["total"] == 0
    assert body["items"] == []


# --- 16-19. RBAC ------------------------------------------------------------


def test_employee_role_cannot_reach_employee_management(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    scoped_user(db, make_user, "worker", "EMPLOYEE", "DEPARTMENT_1")
    headers = login_headers("worker")

    # Even though their business-unit scope would contain employees.
    assert client.get("/api/employees", headers=headers).status_code == 403
    assert client.get("/api/employees/dashboard", headers=headers).status_code == 403
    assert client.post(
        "/api/employees", json={}, headers=headers
    ).status_code == 403


@pytest.mark.parametrize("role_code", ["SUPER_ADMIN", "HR", "MANAGER"])
def test_authorized_roles_can_reach_employee_management(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session,
    role_code: str,
) -> None:
    scoped_user(db, make_user, "person", role_code, "COMPANY_1")

    assert client.get(
        "/api/employees", headers=login_headers("person")
    ).status_code == 200


def test_employee_endpoints_need_authentication(
    client: TestClient, seeded: Session
) -> None:
    assert client.get("/api/employees").status_code == 401
    assert client.get("/api/employees/dashboard").status_code == 401


# --- 20-23. paging, search and filters --------------------------------------


def test_pagination_works(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    scoped_user(db, make_user, "boss", "SUPER_ADMIN", "HQ")
    headers = login_headers("boss")

    first = client.get(
        "/api/employees", headers=headers, params={"page": 1, "page_size": 5}
    ).json()
    second = client.get(
        "/api/employees", headers=headers, params={"page": 2, "page_size": 5}
    ).json()

    assert first["total"] == 22
    assert first["total_pages"] == 5
    assert len(first["items"]) == 5
    # Different rows, and the total does not change with the page.
    assert {r["id"] for r in first["items"]} & {r["id"] for r in second["items"]} == set()
    assert second["total"] == 22


def test_search_works(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    scoped_user(db, make_user, "boss", "SUPER_ADMIN", "HQ")
    headers = login_headers("boss")

    assert list_codes(client, headers, search="Okafor") == {"EMP-005"}
    assert list_codes(client, headers, search="EMP-012") == {"EMP-012"}
    # Case-insensitive, and matches a job title too.
    assert len(list_codes(client, headers, search="branch manager", page_size=100)) == 3


def test_search_cannot_escape_the_scope(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    scoped_user(db, make_user, "lead", "MANAGER", "BRANCH_1")

    # A name that exists, but in Company 2.
    assert list_codes(client, login_headers("lead"), search="Zahra") == set()


def test_business_unit_and_status_filters_work(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    scoped_user(db, make_user, "boss", "SUPER_ADMIN", "HQ")
    headers = login_headers("boss")

    department_1 = unit(db, "DEPARTMENT_1").id
    assert list_codes(client, headers, business_unit_id=department_1, page_size=100) == {
        "EMP-005", "EMP-006", "EMP-007"
    }

    inactive = list_codes(client, headers, employment_status="INACTIVE", page_size=100)
    assert inactive == {"EMP-010", "EMP-020"}

    # Filters combine.
    assert list_codes(
        client, headers, business_unit_id=department_1,
        employment_status="ON_LEAVE", page_size=100,
    ) == {"EMP-007"}


def test_filtering_by_an_out_of_scope_unit_returns_nothing(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    """A filter must narrow the scoped set, never widen it."""
    scoped_user(db, make_user, "lead", "MANAGER", "BRANCH_1")

    assert list_codes(
        client, login_headers("lead"), business_unit_id=unit(db, "DEPARTMENT_5").id
    ) == set()


def test_an_unknown_status_filter_is_rejected(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    scoped_user(db, make_user, "boss", "SUPER_ADMIN", "HQ")

    response = client.get(
        "/api/employees",
        headers=login_headers("boss"),
        params={"employment_status": "RETIRED"},
    )
    assert response.status_code == 400


# --- 24-27. the dashboard ---------------------------------------------------


def test_dashboard_totals_come_from_real_data(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    scoped_user(db, make_user, "boss", "SUPER_ADMIN", "HQ")

    body = client.get(
        "/api/employees/dashboard", headers=login_headers("boss")
    ).json()

    assert body["total_employees"] == 22
    assert body["active_employees"] == 18
    assert body["inactive_employees"] == 2
    assert body["on_leave_employees"] == 2
    assert body["business_units_represented"] == 12
    # The parts add up to the whole - these are counted, not typed in.
    assert (
        body["active_employees"]
        + body["inactive_employees"]
        + body["on_leave_employees"]
        == body["total_employees"]
    )


def test_dashboard_respects_business_unit_scope(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    """HR in Company 1 must not see Company 2 headcount in the totals."""
    scoped_user(db, make_user, "hr", "HR", "COMPANY_1")

    body = client.get("/api/employees/dashboard", headers=login_headers("hr")).json()

    assert body["total_employees"] == 15
    names = {row["name"] for row in body["by_business_unit"]}
    assert "Branch 3" not in names and "Company 2" not in names

    # And the dashboard total matches what the list would return.
    listed = client.get(
        "/api/employees", headers=login_headers("hr"), params={"page_size": 100}
    ).json()
    assert listed["total"] == body["total_employees"]


def test_aggregations_are_correct(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    scoped_user(db, make_user, "lead", "MANAGER", "BRANCH_1")

    body = client.get("/api/employees/dashboard", headers=login_headers("lead")).json()

    by_unit = {row["name"]: row["value"] for row in body["by_business_unit"]}
    assert by_unit == {"Department 1": 3, "Department 2": 3, "Branch 1": 1}
    assert sum(by_unit.values()) == body["total_employees"] == 7

    by_status = {row["name"]: row["value"] for row in body["by_status"]}
    assert by_status == {"Active": 5, "Inactive": 1, "On Leave": 1}


def test_dashboard_widgets_are_served_with_live_values(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    """
    The Stage 6 widget pipeline now carries real numbers: the metadata still
    describes the tiles, the backend fills in the values.
    """
    scoped_user(db, make_user, "boss", "SUPER_ADMIN", "HQ")
    headers = login_headers("boss")

    widgets = client.get(
        "/api/access/dashboards/HEADCOUNT_OVERVIEW/widgets", headers=headers
    ).json()
    assert {w["code"] for w in widgets} >= {"TOTAL_EMPLOYEES", "BY_BUSINESS_UNIT"}
    # The stored config declares a source rather than a number.
    total_widget = next(w for w in widgets if w["code"] == "TOTAL_EMPLOYEES")
    assert total_widget["config_json"]["data_source"] == "employees.total"
    assert "value" not in total_widget["config_json"]

    data = client.get(
        "/api/access/dashboards/HEADCOUNT_OVERVIEW/data", headers=headers
    ).json()
    assert data["TOTAL_EMPLOYEES"]["value"] == 22
    assert data["BY_BUSINESS_UNIT"]["categories"]
    assert data["BY_STATUS"]["series"]


def test_widget_data_is_scoped_per_user(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    scoped_user(db, make_user, "boss", "SUPER_ADMIN", "HQ")
    scoped_user(db, make_user, "lead", "MANAGER", "BRANCH_1")

    boss_data = client.get(
        "/api/access/dashboards/HEADCOUNT_OVERVIEW/data", headers=login_headers("boss")
    ).json()
    lead_data = client.get(
        "/api/access/dashboards/HEADCOUNT_OVERVIEW/data", headers=login_headers("lead")
    ).json()

    assert boss_data["TOTAL_EMPLOYEES"]["value"] == 22
    assert lead_data["TOTAL_EMPLOYEES"]["value"] == 7
