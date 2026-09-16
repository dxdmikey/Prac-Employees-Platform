"""
Tests for the business unit hierarchy and organisational scope.

The seeded development tree, which every test below relies on:

    Headquarters (HQ)
    |-- Company 1
    |     |-- Branch 1 -- Department 1, Department 2
    |     +-- Branch 2 -- Department 3, Department 4
    +-- Company 2
          +-- Branch 3 -- Department 5, Department 6

The rule under test: an assignment grants that unit and everything beneath it,
and never anything above it.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.business_unit import BusinessUnit
from app.models.business_unit_type import BusinessUnitType
from app.models.user import User
from app.services import business_unit_service


def unit(db: Session, code: str) -> BusinessUnit:
    found = db.scalar(select(BusinessUnit).where(BusinessUnit.code == code))
    assert found is not None, f"business unit {code} missing from the seed"
    return found


def assign(db: Session, user: User, *codes: str) -> None:
    for code in codes:
        user.business_units.append(unit(db, code))
    db.commit()


def visible_codes(db: Session, user: User) -> set[str]:
    return {
        u.code for u in business_unit_service.get_user_visible_business_units(db, user)
    }


# --- 1-4. the model itself --------------------------------------------------


def test_business_unit_types_exist(seeded: Session) -> None:
    codes = {t.code for t in business_unit_service.list_business_unit_types(seeded)}
    assert codes == {"HEADQUARTERS", "COMPANY", "BRANCH", "DEPARTMENT"}

    # Types are rows with display names, not a Python enum.
    hq = seeded.scalar(
        select(BusinessUnitType).where(BusinessUnitType.code == "HEADQUARTERS")
    )
    assert hq.name == "Headquarters"


def test_root_business_unit_has_null_parent(seeded: Session) -> None:
    assert unit(seeded, "HQ").parent_id is None


def test_child_references_its_parent(seeded: Session) -> None:
    company_1 = unit(seeded, "COMPANY_1")
    assert company_1.parent_id == unit(seeded, "HQ").id
    assert unit(seeded, "DEPARTMENT_1").parent_id == unit(seeded, "BRANCH_1").id


def test_parent_and_children_relationships_work(seeded: Session) -> None:
    branch_1 = unit(seeded, "BRANCH_1")

    # Down the tree...
    assert {c.code for c in branch_1.children} == {"DEPARTMENT_1", "DEPARTMENT_2"}
    # ...and up it.
    assert branch_1.parent.code == "COMPANY_1"
    assert branch_1.parent.parent.code == "HQ"
    assert unit(seeded, "HQ").parent is None


# --- 5-7. descendant resolution ---------------------------------------------


def test_company_1_returns_its_whole_subtree(seeded: Session) -> None:
    ids = business_unit_service.get_descendant_ids(
        seeded, [unit(seeded, "COMPANY_1").id]
    )
    codes = {u.code for u in seeded.scalars(
        select(BusinessUnit).where(BusinessUnit.id.in_(ids))
    )}

    assert codes == {
        "COMPANY_1", "BRANCH_1", "DEPARTMENT_1", "DEPARTMENT_2",
        "BRANCH_2", "DEPARTMENT_3", "DEPARTMENT_4",
    }
    # Nothing above it, and nothing from the other company.
    assert "HQ" not in codes and "COMPANY_2" not in codes


def test_branch_1_returns_only_its_own_descendants(seeded: Session) -> None:
    ids = business_unit_service.get_descendant_ids(
        seeded, [unit(seeded, "BRANCH_1").id]
    )
    codes = {u.code for u in seeded.scalars(
        select(BusinessUnit).where(BusinessUnit.id.in_(ids))
    )}

    assert codes == {"BRANCH_1", "DEPARTMENT_1", "DEPARTMENT_2"}
    assert "BRANCH_2" not in codes


def test_department_1_is_a_leaf(seeded: Session) -> None:
    below = business_unit_service.get_descendant_ids(
        seeded, [unit(seeded, "DEPARTMENT_1").id], include_self=False
    )
    assert below == set()


# --- 8-12. inherited access -------------------------------------------------


def test_company_1_assignment_grants_the_whole_subtree(
    seeded: Session, make_user
) -> None:
    user = make_user("hr_person", ("HR",))
    assign(seeded, user, "COMPANY_1")

    codes = visible_codes(seeded, user)

    assert "COMPANY_1" in codes        # the unit itself
    assert "BRANCH_1" in codes         # a child
    assert "DEPARTMENT_4" in codes     # a grandchild, two levels down
    assert len(codes) == 7


@pytest.mark.parametrize(
    "target_code", ["COMPANY_1", "BRANCH_1", "BRANCH_2", "DEPARTMENT_1", "DEPARTMENT_4"]
)
def test_can_access_every_unit_beneath_the_assignment(
    seeded: Session, make_user, target_code: str
) -> None:
    user = make_user("hr_person", ("HR",))
    assign(seeded, user, "COMPANY_1")

    assert business_unit_service.can_access_business_unit(
        seeded, user, unit(seeded, target_code).id
    )


def test_a_child_assignment_never_grants_the_parent(
    seeded: Session, make_user
) -> None:
    """The rule that stops scope leaking upwards."""
    user = make_user("lead", ("MANAGER",))
    assign(seeded, user, "BRANCH_1")

    assert visible_codes(seeded, user) == {
        "BRANCH_1", "DEPARTMENT_1", "DEPARTMENT_2"
    }
    for above in ("COMPANY_1", "HQ"):
        assert not business_unit_service.can_access_business_unit(
            seeded, user, unit(seeded, above).id
        )


def test_a_sibling_is_not_visible(seeded: Session, make_user) -> None:
    user = make_user("worker", ("EMPLOYEE",))
    assign(seeded, user, "DEPARTMENT_1")

    assert visible_codes(seeded, user) == {"DEPARTMENT_1"}
    assert not business_unit_service.can_access_business_unit(
        seeded, user, unit(seeded, "DEPARTMENT_2").id
    )


# --- 13-14. multiple assignments --------------------------------------------


def test_multiple_assignments_are_combined(seeded: Session, make_user) -> None:
    user = make_user("split_role", ("MANAGER",))
    assign(seeded, user, "BRANCH_1", "BRANCH_3")

    codes = visible_codes(seeded, user)

    assert codes == {
        "BRANCH_1", "DEPARTMENT_1", "DEPARTMENT_2",
        "BRANCH_3", "DEPARTMENT_5", "DEPARTMENT_6",
    }
    assert "BRANCH_2" not in codes      # still nothing they were not given


def test_removing_an_assignment_removes_the_inherited_scope(
    seeded: Session, make_user
) -> None:
    user = make_user("split_role", ("MANAGER",))
    assign(seeded, user, "BRANCH_1", "BRANCH_3")
    assert "DEPARTMENT_5" in visible_codes(seeded, user)

    business_unit_service.remove_business_unit_from_user(
        seeded, user, unit(seeded, "BRANCH_3")
    )

    codes = visible_codes(seeded, user)
    assert codes == {"BRANCH_1", "DEPARTMENT_1", "DEPARTMENT_2"}
    assert "DEPARTMENT_5" not in codes   # the descendants went with it


# --- 15-16. hierarchy validation --------------------------------------------


def test_self_parenting_is_rejected(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("boss", ("SUPER_ADMIN",))
    branch_1 = unit(seeded, "BRANCH_1")

    response = client.put(
        f"/api/business-units/{branch_1.id}",
        json={"parent_id": branch_1.id},
        headers=login_headers("boss"),
    )

    assert response.status_code == 400
    assert "own parent" in response.json()["detail"]


def test_creating_a_cycle_is_rejected(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """Company 1 may not be moved underneath its own grandchild."""
    make_user("boss", ("SUPER_ADMIN",))
    company_1 = unit(seeded, "COMPANY_1")
    department_1 = unit(seeded, "DEPARTMENT_1")

    response = client.put(
        f"/api/business-units/{company_1.id}",
        json={"parent_id": department_1.id},
        headers=login_headers("boss"),
    )

    assert response.status_code == 400
    assert "cycle" in response.json()["detail"]
    seeded.refresh(company_1)
    assert company_1.parent_id == unit(seeded, "HQ").id   # unchanged


def test_deleting_a_unit_with_children_is_rejected(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("boss", ("SUPER_ADMIN",))

    response = client.delete(
        f"/api/business-units/{unit(seeded, 'BRANCH_1').id}",
        headers=login_headers("boss"),
    )

    assert response.status_code == 400
    assert "beneath it" in response.json()["detail"]


def test_a_leaf_can_be_created_moved_and_deleted(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("boss", ("SUPER_ADMIN",))
    headers = login_headers("boss")
    department_type = seeded.scalar(
        select(BusinessUnitType).where(BusinessUnitType.code == "DEPARTMENT")
    )

    created = client.post(
        "/api/business-units",
        json={
            "code": "DEPARTMENT_TEST",
            "name": "Department Test",
            "business_unit_type_id": department_type.id,
            "parent_id": unit(seeded, "BRANCH_1").id,
        },
        headers=headers,
    )
    assert created.status_code == 201
    new_id = created.json()["id"]

    moved = client.put(
        f"/api/business-units/{new_id}",
        json={"parent_id": unit(seeded, "BRANCH_2").id},
        headers=headers,
    )
    assert moved.status_code == 200
    assert moved.json()["parent_id"] == unit(seeded, "BRANCH_2").id

    assert client.delete(
        f"/api/business-units/{new_id}", headers=headers
    ).status_code == 204


# --- 17-18. RBAC *and* scope, on the demonstration endpoint -----------------


def test_access_check_requires_the_permission(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    """
    Question 1 - WHAT. A user with the right scope but no VIEW permission is
    still refused.
    """
    user = make_user("no_perms", ())          # no role at all, so no permissions
    assign(db, user, "COMPANY_1")

    response = client.get(
        f"/api/business-units/{unit(seeded, 'BRANCH_1').id}/access-check",
        headers=login_headers("no_perms"),
    )

    assert response.status_code == 403
    assert "VIEW permission" in response.json()["detail"]


def test_access_check_requires_business_unit_scope(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    """
    Question 2 - WHERE. A user with VIEW but the wrong scope is also refused,
    and the message says which half failed.
    """
    user = make_user("worker", ("EMPLOYEE",))   # EMPLOYEE holds VIEW
    assign(db, user, "DEPARTMENT_1")

    outside = client.get(
        f"/api/business-units/{unit(seeded, 'DEPARTMENT_2').id}/access-check",
        headers=login_headers("worker"),
    )
    assert outside.status_code == 403
    assert "outside your organisational scope" in outside.json()["detail"]

    inside = client.get(
        f"/api/business-units/{unit(seeded, 'DEPARTMENT_1').id}/access-check",
        headers=login_headers("worker"),
    )
    assert inside.status_code == 200
    assert inside.json()["access"] is True
    assert inside.json()["reason"] == "directly assigned"


def test_access_check_reports_inherited_access(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    user = make_user("hr_person", ("HR",))
    assign(db, user, "COMPANY_1")

    response = client.get(
        f"/api/business-units/{unit(seeded, 'DEPARTMENT_4').id}/access-check",
        headers=login_headers("hr_person"),
    )

    assert response.status_code == 200
    assert response.json()["reason"] == "inherited from a business unit above it"


def test_access_check_needs_authentication(client: TestClient, seeded: Session) -> None:
    assert client.get("/api/business-units/1/access-check").status_code == 401


# --- 19. Super Admin --------------------------------------------------------


def test_super_admin_still_needs_an_assignment_for_scope(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    """
    Scope is not implied by a role - not even Super Admin.

    A Super Admin manages the platform, which is why the management endpoints
    are open to them; but *organisational* scope still comes from an
    assignment. Give them Headquarters and they see the whole tree.
    """
    boss = make_user("boss", ("SUPER_ADMIN",))
    headers = login_headers("boss")

    # Management access: yes, immediately.
    assert client.get("/api/business-units/tree", headers=headers).status_code == 200
    # Organisational scope: not yet.
    assert client.get(
        f"/api/business-units/{unit(seeded, 'HQ').id}/access-check", headers=headers
    ).status_code == 403

    assign(db, boss, "HQ")

    assert client.get(
        f"/api/business-units/{unit(seeded, 'HQ').id}/access-check", headers=headers
    ).status_code == 200
    assert len(visible_codes(db, boss)) == 12      # the entire organisation


# --- endpoint protection ----------------------------------------------------


def test_management_endpoints_are_closed_to_ordinary_roles(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("worker", ("EMPLOYEE",))
    headers = login_headers("worker")

    assert client.get("/api/business-units", headers=headers).status_code == 403
    assert client.get("/api/business-units/tree", headers=headers).status_code == 403
    assert client.get("/api/business-unit-types", headers=headers).status_code == 403
    assert client.post(
        "/api/business-units",
        json={"code": "X", "name": "X", "business_unit_type_id": 1},
        headers=headers,
    ).status_code == 403


def test_assignment_endpoints_are_closed_to_ordinary_roles(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    worker = make_user("worker", ("EMPLOYEE",))
    headers = login_headers("worker")

    assert client.get(
        f"/api/users/{worker.id}/business-units", headers=headers
    ).status_code == 403
    assert client.post(
        f"/api/users/{worker.id}/business-units",
        json={"business_unit_id": 1},
        headers=headers,
    ).status_code == 403


def test_admin_can_assign_and_remove_a_business_unit(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    make_user("boss", ("SUPER_ADMIN",))
    target = make_user("worker", ("EMPLOYEE",))
    headers = login_headers("boss")
    branch_1 = unit(seeded, "BRANCH_1")

    assigned = client.post(
        f"/api/users/{target.id}/business-units",
        json={"business_unit_id": branch_1.id},
        headers=headers,
    )
    assert assigned.status_code == 201
    assert [u["code"] for u in assigned.json()] == ["BRANCH_1"]

    # The assignment immediately widens what that user can reach.
    assert client.get(
        f"/api/business-units/{unit(seeded, 'DEPARTMENT_2').id}/access-check",
        headers=login_headers("worker"),
    ).status_code == 200

    removed = client.delete(
        f"/api/users/{target.id}/business-units/{branch_1.id}", headers=headers
    )
    assert removed.status_code == 200
    assert removed.json() == []
    assert client.get(
        f"/api/business-units/{unit(seeded, 'DEPARTMENT_2').id}/access-check",
        headers=login_headers("worker"),
    ).status_code == 403


# --- self-service scope endpoint --------------------------------------------


def test_my_business_units_separates_assigned_from_visible(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    user = make_user("lead", ("MANAGER",))
    assign(db, user, "BRANCH_1")

    body = client.get(
        "/api/access/business-units", headers=login_headers("lead")
    ).json()

    assert [u["code"] for u in body["assigned"]] == ["BRANCH_1"]
    assert {u["code"] for u in body["visible"]} == {
        "BRANCH_1", "DEPARTMENT_1", "DEPARTMENT_2"
    }


def test_a_user_with_no_assignment_sees_nothing(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("nowhere", ("EMPLOYEE",))

    body = client.get(
        "/api/access/business-units", headers=login_headers("nowhere")
    ).json()

    assert body["assigned"] == []
    assert body["visible"] == []


# --- the tree endpoint ------------------------------------------------------


def test_tree_endpoint_returns_the_nested_organisation(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    make_user("boss", ("SUPER_ADMIN",))

    tree = client.get(
        "/api/business-units/tree", headers=login_headers("boss")
    ).json()

    assert len(tree) == 1                       # a single root
    hq = tree[0]
    assert hq["code"] == "HQ"
    assert hq["business_unit_type_name"] == "Headquarters"

    companies = {c["code"]: c for c in hq["children"]}
    assert set(companies) == {"COMPANY_1", "COMPANY_2"}

    branch_1 = next(
        b for b in companies["COMPANY_1"]["children"] if b["code"] == "BRANCH_1"
    )
    assert {d["code"] for d in branch_1["children"]} == {
        "DEPARTMENT_1", "DEPARTMENT_2"
    }


# --- 20. RBAC is untouched --------------------------------------------------


def test_application_rbac_is_unaffected_by_business_unit_scope(
    client: TestClient, seeded: Session, make_user, login_headers, db: Session
) -> None:
    """
    Application access and organisational scope are independent.

    Giving someone a business unit must not change which applications they can
    open, and taking it away must not either.
    """
    user = make_user("worker", ("EMPLOYEE",))
    headers = login_headers("worker")

    def application_codes() -> set[str]:
        return {
            a["code"]
            for a in client.get("/api/access/me", headers=headers).json()["applications"]
        }

    before = application_codes()
    assert before == {
        "LEAVE_MANAGEMENT", "PAYROLL", "ATTENDANCE_TIMESHEET", "EXPENSE_MANAGEMENT"
    }

    assign(db, user, "COMPANY_1")
    assert application_codes() == before        # scope changed, RBAC did not

    business_unit_service.remove_business_unit_from_user(
        db, user, unit(db, "COMPANY_1")
    )
    assert application_codes() == before
