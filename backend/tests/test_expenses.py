"""
Tests for Expense Management (Stage 11).

Four things are being proven:

  1. the claim rules work - positive amounts, active categories, drafts only,
  2. **money is exact**. Amounts are Decimal end to end, and a total built
     from many claims equals the total a person would get on paper,
  3. **the workflow is metadata**, including the case that forced the actor
     marker onto the transition: Cancel leaves SUBMITTED, a state that is
     *not* owner-held, and still belongs to the claimant,
  4. **every read is scoped**, and an uploaded receipt is no way around it.

Expectations are computed from the seed generator rather than copied from it,
so the tests survive both a changed fixture and a database somebody has been
clicking around in.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.metadata import seed
from app.models.business_unit import BusinessUnit
from app.models.employee import Employee
from app.models.expense import Expense
from app.models.expense_attachment import ExpenseAttachment
from app.models.expense_category import ExpenseCategory
from app.models.user import User
from app.models.workflow_history import WorkflowHistory
from app.models.workflow_state import WorkflowState
from app.services import expense_service
from app.services.expense_service import ExpenseError, ExpenseNotVisible
from app.workflows import engine, ownership
from app.workflows.exceptions import (
    TransitionNotAuthorized,
    TransitionNotAvailable,
    TransitionNotFound,
)

WORKFLOW = "EXPENSE_APPROVAL"

_UNIT_PARENT = {s.code: s.parent_code for s in seed.BUSINESS_UNITS}
_EMPLOYEE_NAME = {s.code: f"{s.first_name} {s.last_name}" for s in seed.EMPLOYEES}
_UNIT_NAME = {s.code: s.name for s in seed.BUSINESS_UNITS}


def units_under(unit_code: str) -> set[str]:
    found = {unit_code}
    while True:
        grown = found | {u for u, parent in _UNIT_PARENT.items() if parent in found}
        if grown == found:
            return found
        found = grown


def assert_scoped_to(rows: list[dict], unit_code: str) -> None:
    """
    Every visible row belongs to a unit at or below `unit_code`.

    Structural rather than a fixed list: the fixtures are the floor, not the
    ceiling, and a developer's own claims must not turn the suite red. What
    can never happen, however much real data is present, is a row from outside
    the caller's scope appearing here.
    """
    allowed = {_UNIT_NAME[code] for code in units_under(unit_code)}
    leaked = {r["business_unit"]["name"] for r in rows} - allowed
    assert not leaked, f"rows leaked from outside {unit_code}: {sorted(leaked)}"


def unit(db: Session, code: str) -> BusinessUnit:
    return db.scalar(select(BusinessUnit).where(BusinessUnit.code == code))


def category(db: Session, code: str = "MEALS") -> ExpenseCategory:
    return db.scalar(select(ExpenseCategory).where(ExpenseCategory.code == code))


_counter = {"n": 0}


def staff(
    db: Session, make_user, username: str, role: str, unit_code: str,
    *, with_employee: bool = True,
) -> User:
    user = make_user(username, (role,))
    user.business_units.append(unit(db, unit_code))
    db.commit()

    if with_employee:
        _counter["n"] += 1
        n = _counter["n"]
        db.add(Employee(
            employee_code=f"EMP-EX{n:03d}",
            user_id=user.id,
            first_name=username.capitalize(),
            last_name="Exptest",
            email=f"{username}.exptest{n}@example.local",
            business_unit_id=unit(db, unit_code).id,
        ))
        db.commit()
    return user


def make_claim(
    db: Session, user: User, *, amount: str = "42.50", when: date | None = None,
    category_code: str = "MEALS", currency: str = "USD",
    description: str = "Test claim", merchant: str | None = "Test Merchant",
) -> Expense:
    """A claim created through the service, so it starts where the workflow says."""
    return expense_service.create_expense(db, user, {
        "category_id": category(db, category_code).id,
        "expense_date": when or date.today(),
        "amount": Decimal(amount),
        "currency": currency,
        "merchant": merchant,
        "description": description,
        "reference_number": "RCT-TEST",
    })


def history_count(db: Session, expense: Expense) -> int:
    return db.scalar(
        select(func.count()).select_from(WorkflowHistory).where(
            WorkflowHistory.entity_type == "expenses",
            WorkflowHistory.entity_id == expense.id,
        )
    )


def codes(transitions) -> set[str]:
    return {t.code for t in transitions}


def rows_for(client: TestClient, headers, **params) -> list[dict]:
    params.setdefault("page_size", 100)
    response = client.get("/api/expenses", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


# A one-pixel PNG, so the upload tests exercise a real file rather than a
# string pretending to be one.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6360000002000100ffff03000006"
    "000557bfabd40000000049454e44ae426082"
)


# ===========================================================================
# Categories
# ===========================================================================


def test_categories_are_rows_not_a_hardcoded_list(seeded: Session) -> None:
    codes_found = {c.code for c in seeded.scalars(select(ExpenseCategory))}
    assert {"TRAVEL", "MEALS", "HOTEL", "TRANSPORT", "TRAINING", "OTHER"} <= codes_found


def test_a_new_category_needs_no_code_change(seeded: Session) -> None:
    fresh = ExpenseCategory(code="ENTERTAINMENT", name="Client Entertainment")
    seeded.add(fresh)
    seeded.commit()

    assert fresh.id is not None
    assert fresh.is_active is True


def test_category_code_must_be_unique(seeded: Session) -> None:
    from sqlalchemy.exc import IntegrityError

    seeded.add(ExpenseCategory(code="TRAVEL", name="Travel Again"))
    with pytest.raises(IntegrityError):
        seeded.commit()
    seeded.rollback()


def test_the_categories_endpoint_returns_only_active_ones(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "catuser", "EMPLOYEE", "DEPARTMENT_1")
    seeded.add(ExpenseCategory(code="RETIRED", name="Retired Category",
                               is_active=False))
    seeded.commit()

    body = client.get(
        "/api/expenses/categories", headers=login_headers("catuser")
    ).json()
    found = {c["code"] for c in body}

    assert "TRAVEL" in found
    assert "RETIRED" not in found


def test_an_inactive_category_cannot_be_claimed_against(
    seeded: Session, make_user
) -> None:
    user = staff(seeded, make_user, "retiredcat", "EMPLOYEE", "DEPARTMENT_1")
    retired = ExpenseCategory(code="GONE", name="Gone", is_active=False)
    seeded.add(retired)
    seeded.commit()

    with pytest.raises(ExpenseError):
        expense_service.create_expense(seeded, user, {
            "category_id": retired.id,
            "expense_date": date.today(),
            "amount": Decimal("10.00"),
            "currency": "USD",
            "description": "Nope",
        })


def test_an_unknown_category_is_refused(seeded: Session, make_user) -> None:
    user = staff(seeded, make_user, "ghostcat", "EMPLOYEE", "DEPARTMENT_1")

    with pytest.raises(ExpenseError):
        expense_service.create_expense(seeded, user, {
            "category_id": 999_999,
            "expense_date": date.today(),
            "amount": Decimal("10.00"),
            "currency": "USD",
            "description": "Nope",
        })


# ===========================================================================
# Money
# ===========================================================================


def test_amounts_are_stored_and_returned_as_exact_decimals(
    seeded: Session, make_user
) -> None:
    """
    The reason the column is Numeric and not Float.

    0.10 cannot be represented exactly in binary floating point. Ten of them
    stored as floats sum to 0.9999999999999999; stored as Decimal they sum to
    exactly 1.00, which is the number a person expects.
    """
    user = staff(seeded, make_user, "penny", "EMPLOYEE", "DEPARTMENT_1")
    for index in range(10):
        make_claim(seeded, user, amount="0.10",
                   when=date.today() - timedelta(days=index))

    total = seeded.scalar(
        select(func.sum(Expense.amount)).where(
            Expense.employee_id == expense_service.get_own_employee(seeded, user).id
        )
    )
    assert isinstance(total, Decimal)
    assert total == Decimal("1.00")


@pytest.mark.parametrize("amount", ["0", "-1.00", "-0.01"])
def test_a_non_positive_amount_is_refused(amount: str) -> None:
    with pytest.raises(ExpenseError):
        expense_service.validate_amount(Decimal(amount))


def test_an_amount_is_quantized_to_the_penny() -> None:
    assert expense_service.validate_amount(Decimal("10.005")) == Decimal("10.01")
    assert expense_service.validate_amount(Decimal("10")) == Decimal("10.00")


def test_the_api_refuses_a_zero_amount(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "zeroclaim", "EMPLOYEE", "DEPARTMENT_1")

    response = client.post(
        "/api/expenses",
        headers=login_headers("zeroclaim"),
        json={
            "category_id": category(seeded).id,
            "expense_date": date.today().isoformat(),
            "amount": "0.00",
            "description": "Nothing",
        },
    )
    # Refused by the schema before the service is even reached.
    assert response.status_code == 422


def test_required_fields_are_enforced(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "missing", "EMPLOYEE", "DEPARTMENT_1")

    response = client.post(
        "/api/expenses",
        headers=login_headers("missing"),
        json={"category_id": category(seeded).id},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("code", ["usd", "EUR", "gbp"])
def test_supported_currencies_are_accepted_case_insensitively(code: str) -> None:
    assert expense_service.validate_currency(code) == code.upper()


def test_an_unsupported_currency_is_refused() -> None:
    with pytest.raises(ExpenseError):
        expense_service.validate_currency("XYZ")


def test_currency_defaults_when_not_given() -> None:
    assert expense_service.validate_currency(None) == "USD"


# ===========================================================================
# Creating and editing
# ===========================================================================


def test_an_employee_can_raise_their_own_claim(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "claimant", "EMPLOYEE", "DEPARTMENT_1")

    response = client.post(
        "/api/expenses",
        headers=login_headers("claimant"),
        json={
            "category_id": category(seeded, "TRAVEL").id,
            "expense_date": date.today().isoformat(),
            "amount": "129.99",
            "currency": "USD",
            "merchant": "Northwind Air",
            "description": "Flight to the client site",
            "reference_number": "RCT-1",
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert Decimal(str(body["amount"])) == Decimal("129.99")
    assert body["state_code"] == "DRAFT"
    assert body["is_editable"] is True
    assert body["employee"]["name"] == "Claimant Exptest"
    assert body["attachments"] == []


def test_an_employee_id_from_the_browser_is_ignored(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "sneaky", "EMPLOYEE", "DEPARTMENT_1")
    victim = seeded.scalar(select(Employee).where(Employee.employee_code == "EMP-006"))

    response = client.post(
        "/api/expenses",
        headers=login_headers("sneaky"),
        json={
            "category_id": category(seeded).id,
            "expense_date": date.today().isoformat(),
            "amount": "10.00",
            "description": "Not mine",
            "employee_id": victim.id,
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["employee"]["name"] == "Sneaky Exptest"


def test_a_user_with_no_employee_record_cannot_claim(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "accountless", "EMPLOYEE", "DEPARTMENT_1",
          with_employee=False)

    response = client.post(
        "/api/expenses",
        headers=login_headers("accountless"),
        json={
            "category_id": category(seeded).id,
            "expense_date": date.today().isoformat(),
            "amount": "10.00",
            "description": "Anything",
        },
    )
    assert response.status_code == 409
    assert "employee record" in response.json()["detail"]


def test_an_employee_can_edit_their_draft(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "editor", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, user, amount="10.00")

    response = client.patch(
        f"/api/expenses/{claim.id}",
        headers=login_headers("editor"),
        json={"amount": "25.75", "merchant": "Updated Merchant"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert Decimal(str(body["amount"])) == Decimal("25.75")
    assert body["merchant"] == "Updated Merchant"


def test_an_employee_cannot_edit_a_submitted_claim(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "hasty", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, user)
    expense_service.execute_transition(seeded, user, claim.id, "SUBMIT", None)

    response = client.patch(
        f"/api/expenses/{claim.id}",
        headers=login_headers("hasty"),
        json={"amount": "999.00"},
    )

    assert response.status_code == 400
    assert "no longer" in response.json()["detail"]


def test_an_employee_cannot_edit_somebody_elses_draft(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    worker = staff(seeded, make_user, "junior", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, worker)
    staff(seeded, make_user, "boss", "MANAGER", "BRANCH_1")

    response = client.patch(
        f"/api/expenses/{claim.id}",
        headers=login_headers("boss"),
        json={"amount": "1.00"},
    )
    assert response.status_code == 403


def test_a_client_supplied_state_is_ignored(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "forger", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, user)
    approved = seeded.scalar(
        select(WorkflowState).where(
            WorkflowState.workflow_id == claim.workflow_id,
            WorkflowState.code == "APPROVED",
        )
    )

    response = client.patch(
        f"/api/expenses/{claim.id}",
        headers=login_headers("forger"),
        json={"current_state_id": approved.id, "workflow_id": 1},
    )

    assert response.status_code == 200, response.text
    assert response.json()["state_code"] == "DRAFT"
    seeded.refresh(claim)
    assert claim.current_state_id != approved.id


def test_expense_details_are_readable_by_their_owner(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "reader", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, user, description="Readable claim")

    body = client.get(
        f"/api/expenses/{claim.id}", headers=login_headers("reader")
    ).json()

    assert body["id"] == claim.id
    assert body["description"] == "Readable claim"
    assert body["category"]["name"] == "Meals"


# ===========================================================================
# The workflow
# ===========================================================================


def test_the_expense_workflow_is_rows_not_code(seeded: Session) -> None:
    workflow = engine.get_workflow(seeded, WORKFLOW)

    states = {
        s.code: (s.is_initial, s.is_final, s.is_owner_held)
        for s in engine.get_states(seeded, workflow)
    }
    transitions = {
        t.code: (t.from_state.code, t.to_state.code, t.actor)
        for t in engine.get_transitions(seeded, workflow)
    }

    assert states == {
        #            initial  final  owner-held
        "DRAFT":     (True,   False, True),
        # SUBMITTED is NOT owner-held: it genuinely sits with the approver,
        # which is what the pending queue counts.
        "SUBMITTED": (False,  False, False),
        "APPROVED":  (False,  True,  False),
        "REJECTED":  (False,  False, True),
        "CANCELLED": (False,  True,  False),
    }
    assert transitions == {
        "SUBMIT":  ("DRAFT", "SUBMITTED", "OWNER"),
        # ...and yet Cancel leaves SUBMITTED and belongs to the claimant.
        # That pair is why the actor marker had to move onto the transition.
        "CANCEL":  ("SUBMITTED", "CANCELLED", "OWNER"),
        "APPROVE": ("SUBMITTED", "APPROVED", "OTHER"),
        "REJECT":  ("SUBMITTED", "REJECTED", "OTHER"),
        "REVISE":  ("REJECTED", "DRAFT", "OWNER"),
    }


def test_a_claim_starts_in_the_workflows_initial_state(
    seeded: Session, make_user
) -> None:
    user = staff(seeded, make_user, "starter", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, user)

    workflow = engine.get_workflow(seeded, WORKFLOW)
    assert claim.current_state_id == engine.get_initial_state(seeded, workflow).id
    assert claim.current_state.is_initial is True


def test_submit_moves_a_draft_to_submitted(seeded: Session, make_user) -> None:
    user = staff(seeded, make_user, "submitter", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, user)

    updated = expense_service.execute_transition(seeded, user, claim.id, "SUBMIT", None)
    assert updated.current_state.code == "SUBMITTED"


def test_a_manager_can_approve_and_reject(seeded: Session, make_user) -> None:
    manager = staff(seeded, make_user, "decider", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "doer", "EMPLOYEE", "DEPARTMENT_1")

    approved = make_claim(seeded, worker, when=date(2026, 9, 1))
    rejected = make_claim(seeded, worker, when=date(2026, 9, 2))
    for claim in (approved, rejected):
        expense_service.execute_transition(seeded, worker, claim.id, "SUBMIT", None)

    a = expense_service.execute_transition(
        seeded, manager, approved.id, "APPROVE", "Within policy."
    )
    r = expense_service.execute_transition(
        seeded, manager, rejected.id, "REJECT", "Receipt missing."
    )

    assert a.current_state.code == "APPROVED"
    assert a.current_state.is_final is True
    assert r.current_state.code == "REJECTED"
    assert r.current_state.is_final is False   # something still leaves it


def test_a_claimant_can_cancel_their_own_submitted_claim(
    seeded: Session, make_user
) -> None:
    """
    **The case that forced the actor marker onto the transition.**

    SUBMITTED is not owner-held - it is on the approver's desk, and the
    pending queue is right to count it there. Cancel leaves that same state
    and still belongs to the claimant. A state-level flag cannot say both
    things at once, which is why `workflow_transitions.actor` exists.
    """
    manager = staff(seeded, make_user, "approver", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "withdrawer", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, worker)
    expense_service.execute_transition(seeded, worker, claim.id, "SUBMIT", None)

    # Both hold at the same moment, on the same record.
    assert codes(
        expense_service.available_transitions(seeded, worker, claim.id)
    ) == {"CANCEL"}
    assert codes(
        expense_service.available_transitions(seeded, manager, claim.id)
    ) == {"APPROVE", "REJECT"}

    cancelled = expense_service.execute_transition(
        seeded, worker, claim.id, "CANCEL", "Booked to the project instead."
    )
    assert cancelled.current_state.code == "CANCELLED"
    assert cancelled.current_state.is_final is True


def test_a_manager_cannot_cancel_somebody_elses_claim(
    seeded: Session, make_user
) -> None:
    """Cancel is marked OWNER, so an approver is never offered it."""
    manager = staff(seeded, make_user, "notmine", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "ownerof", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, worker)
    expense_service.execute_transition(seeded, worker, claim.id, "SUBMIT", None)

    with pytest.raises(TransitionNotAuthorized):
        expense_service.execute_transition(seeded, manager, claim.id, "CANCEL", None)

    seeded.refresh(claim)
    assert claim.current_state.code == "SUBMITTED"


def test_a_rejected_claim_returns_to_its_owner_to_revise(
    seeded: Session, make_user
) -> None:
    manager = staff(seeded, make_user, "rejecter", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "reviser", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, worker)
    expense_service.execute_transition(seeded, worker, claim.id, "SUBMIT", None)
    expense_service.execute_transition(seeded, manager, claim.id, "REJECT", "No.")

    assert codes(
        expense_service.available_transitions(seeded, worker, claim.id)
    ) == {"REVISE"}
    assert codes(
        expense_service.available_transitions(seeded, manager, claim.id)
    ) == set()

    revised = expense_service.execute_transition(
        seeded, worker, claim.id, "REVISE", None
    )
    assert revised.current_state.code == "DRAFT"
    assert revised.current_state.is_initial is True


def test_a_rejected_claim_is_not_editable_until_revised(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    manager = staff(seeded, make_user, "gate", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "author", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, worker)
    expense_service.execute_transition(seeded, worker, claim.id, "SUBMIT", None)
    expense_service.execute_transition(seeded, manager, claim.id, "REJECT", "No.")
    headers = login_headers("author")

    blocked = client.patch(
        f"/api/expenses/{claim.id}", headers=headers, json={"amount": "5.00"}
    )
    assert blocked.status_code == 400

    client.post(
        f"/api/expenses/{claim.id}/transition",
        headers=headers, json={"transition_code": "REVISE"},
    )
    allowed = client.patch(
        f"/api/expenses/{claim.id}", headers=headers, json={"amount": "5.00"}
    )
    assert allowed.status_code == 200
    assert Decimal(str(allowed.json()["amount"])) == Decimal("5.00")


def test_a_full_round_trip_reaches_approval(seeded: Session, make_user) -> None:
    """Draft, submitted, rejected, revised, resubmitted, approved."""
    manager = staff(seeded, make_user, "roundboss", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "roundworker", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, worker)

    for actor, code in (
        (worker, "SUBMIT"), (manager, "REJECT"), (worker, "REVISE"),
        (worker, "SUBMIT"), (manager, "APPROVE"),
    ):
        expense_service.execute_transition(seeded, actor, claim.id, code, None)

    seeded.refresh(claim)
    assert claim.current_state.code == "APPROVED"
    assert history_count(seeded, claim) == 6      # opening plus five moves


def test_nobody_approves_their_own_claim(seeded: Session, make_user) -> None:
    manager = staff(seeded, make_user, "selfish", "MANAGER", "BRANCH_1")
    claim = make_claim(seeded, manager)
    expense_service.execute_transition(seeded, manager, claim.id, "SUBMIT", None)

    # Offered Cancel, because that is theirs - but never Approve.
    assert codes(
        expense_service.available_transitions(seeded, manager, claim.id)
    ) == {"CANCEL"}

    with pytest.raises(TransitionNotAuthorized):
        expense_service.execute_transition(seeded, manager, claim.id, "APPROVE", None)

    seeded.refresh(claim)
    assert claim.current_state.code == "SUBMITTED"


def test_a_transition_the_metadata_does_not_define_is_refused(
    seeded: Session, make_user
) -> None:
    """There is no DRAFT -> APPROVED arrow, so the jump cannot be made."""
    manager = staff(seeded, make_user, "jumper", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "jumped", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, worker)

    with pytest.raises(TransitionNotAvailable):
        expense_service.execute_transition(seeded, manager, claim.id, "APPROVE", None)

    seeded.refresh(claim)
    assert claim.current_state.code == "DRAFT"


def test_an_unknown_transition_code_is_refused(seeded: Session, make_user) -> None:
    manager = staff(seeded, make_user, "inventor", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "invented", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, worker)
    expense_service.execute_transition(seeded, worker, claim.id, "SUBMIT", None)

    with pytest.raises(TransitionNotFound):
        expense_service.execute_transition(
            seeded, manager, claim.id, "RUBBER_STAMP", None
        )


def test_an_employee_cannot_approve_a_colleagues_claim(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    worker = staff(seeded, make_user, "peer1", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, worker)
    expense_service.execute_transition(seeded, worker, claim.id, "SUBMIT", None)
    staff(seeded, make_user, "peer2", "EMPLOYEE", "DEPARTMENT_1")

    response = client.post(
        f"/api/expenses/{claim.id}/transition",
        headers=login_headers("peer2"),
        json={"transition_code": "APPROVE"},
    )

    assert response.status_code == 403
    seeded.refresh(claim)
    assert claim.current_state.code == "SUBMITTED"


def test_an_out_of_scope_manager_cannot_approve(
    seeded: Session, make_user
) -> None:
    worker = staff(seeded, make_user, "local", "EMPLOYEE", "DEPARTMENT_1")
    outsider = staff(seeded, make_user, "distant", "MANAGER", "BRANCH_3")
    claim = make_claim(seeded, worker)
    expense_service.execute_transition(seeded, worker, claim.id, "SUBMIT", None)

    # Refused by the scope check in the service, not only by the route.
    with pytest.raises(ExpenseNotVisible):
        expense_service.execute_transition(seeded, outsider, claim.id, "APPROVE", None)

    seeded.refresh(claim)
    assert claim.current_state.code == "SUBMITTED"


def test_the_shared_ownership_helper_reads_the_actor(seeded: Session) -> None:
    """One helper now serves leave, timesheets and expenses alike."""
    workflow = engine.get_workflow(seeded, WORKFLOW)
    transitions = engine.get_transitions(seeded, workflow)
    by_code = {t.code: t for t in transitions}

    assert ownership.is_owner_action(by_code["CANCEL"]) is True
    assert ownership.is_owner_action(by_code["APPROVE"]) is False

    as_owner = codes(ownership.filter_for_caller(transitions, is_owner=True))
    as_other = codes(ownership.filter_for_caller(transitions, is_owner=False))
    assert as_owner == {"SUBMIT", "CANCEL", "REVISE"}
    assert as_other == {"APPROVE", "REJECT"}
    assert as_owner & as_other == set()


def test_the_demo_workflow_is_untouched_by_the_actor_column(seeded: Session) -> None:
    """
    ANY is the default, so Stage 7's demo workflow behaves exactly as before -
    which is the whole reason the column has a default at all.
    """
    workflow = engine.get_workflow(seeded, "EXPENSE_APPROVAL_DEMO")
    transitions = engine.get_transitions(seeded, workflow)

    assert all(t.actor == "ANY" for t in transitions)
    assert all(ownership.is_owner_action(t) is None for t in transitions)
    # ANY means both sides see it.
    assert codes(ownership.filter_for_caller(transitions, is_owner=True)) == codes(
        ownership.filter_for_caller(transitions, is_owner=False)
    )


# ===========================================================================
# History and transaction safety
# ===========================================================================


def test_history_is_written_for_every_successful_transition(
    seeded: Session, make_user
) -> None:
    manager = staff(seeded, make_user, "logger", "MANAGER", "BRANCH_1")
    worker = staff(seeded, make_user, "logged", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, worker)

    assert history_count(seeded, claim) == 1      # the opening entry

    expense_service.execute_transition(seeded, worker, claim.id, "SUBMIT", None)
    expense_service.execute_transition(
        seeded, manager, claim.id, "REJECT", "Itemised receipt needed."
    )

    entries = engine.get_history(seeded, claim)
    assert [e.to_state.code for e in entries] == ["DRAFT", "SUBMITTED", "REJECTED"]
    assert entries[0].from_state is None and entries[0].transition is None
    assert entries[1].performed_by_user_id == worker.id
    assert entries[2].performed_by_user_id == manager.id
    # The rejection reason lives on the history row, not on the claim.
    assert entries[2].comments == "Itemised receipt needed."
    assert entries[0].entity_type == "expenses"


def test_a_failed_transition_writes_no_history_and_changes_no_state(
    seeded: Session, make_user
) -> None:
    worker = staff(seeded, make_user, "steady", "EMPLOYEE", "DEPARTMENT_1")
    outsider = staff(seeded, make_user, "outsider", "MANAGER", "BRANCH_3")
    claim = make_claim(seeded, worker)
    expense_service.execute_transition(seeded, worker, claim.id, "SUBMIT", None)

    before_state = claim.current_state_id
    before_history = history_count(seeded, claim)

    with pytest.raises(ExpenseNotVisible):
        expense_service.execute_transition(seeded, outsider, claim.id, "APPROVE", None)

    seeded.refresh(claim)
    assert claim.current_state_id == before_state
    assert history_count(seeded, claim) == before_history


def test_seeded_claims_carry_a_complete_history(seeded: Session) -> None:
    cancelled_state = seeded.scalar(
        select(WorkflowState)
        .where(WorkflowState.code == "CANCELLED")
        .where(WorkflowState.workflow.has(code=WORKFLOW))
    )
    claim = seeded.scalar(
        select(Expense).where(Expense.current_state_id == cancelled_state.id).limit(1)
    )
    assert claim is not None

    entries = engine.get_history(seeded, claim)
    assert [e.to_state.code for e in entries] == ["DRAFT", "SUBMITTED", "CANCELLED"]
    # Cancelled by the claimant, not by an approver - the fixture agrees with
    # the actor marking.
    assert entries[2].performed_by_user_id == entries[1].performed_by_user_id


# ===========================================================================
# Business-unit scope
# ===========================================================================


def test_an_employee_sees_only_their_own_claims(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """Same department, and still invisible: an EMPLOYEE has no APPROVE."""
    colleague = staff(seeded, make_user, "colleague", "EMPLOYEE", "DEPARTMENT_1")
    theirs = make_claim(seeded, colleague)
    staff(seeded, make_user, "nosy", "EMPLOYEE", "DEPARTMENT_1")
    headers = login_headers("nosy")

    assert rows_for(client, headers) == []
    assert client.get(f"/api/expenses/{theirs.id}", headers=headers).status_code == 403


def test_a_manager_sees_their_unit_and_its_descendants(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "branchboss", "MANAGER", "BRANCH_1", with_employee=False)

    rows = rows_for(client, login_headers("branchboss"))
    names = {r["employee"]["name"] for r in rows}

    assert_scoped_to(rows, "BRANCH_1")
    assert _EMPLOYEE_NAME["EMP-012"] not in names   # Branch 2
    assert _EMPLOYEE_NAME["EMP-019"] not in names   # Company 2


def test_scope_never_flows_upward(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "deptboss", "MANAGER", "DEPARTMENT_1", with_employee=False)

    rows = rows_for(client, login_headers("deptboss"))
    assert_scoped_to(rows, "DEPARTMENT_1")
    assert _EMPLOYEE_NAME["EMP-004"] not in {r["employee"]["name"] for r in rows}


def test_hr_at_a_company_sees_the_whole_company(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "hr", "HR", "COMPANY_1", with_employee=False)

    rows = rows_for(client, login_headers("hr"))
    assert_scoped_to(rows, "COMPANY_1")
    assert len(rows) > 0


def test_an_out_of_scope_claim_cannot_be_reached_by_id(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    outsider = staff(seeded, make_user, "far", "EMPLOYEE", "DEPARTMENT_5")
    theirs = make_claim(seeded, outsider)
    expense_service.execute_transition(seeded, outsider, theirs.id, "SUBMIT", None)
    staff(seeded, make_user, "near", "MANAGER", "BRANCH_1", with_employee=False)
    headers = login_headers("near")

    assert client.get(f"/api/expenses/{theirs.id}", headers=headers).status_code == 403
    assert client.get(
        f"/api/expenses/{theirs.id}/history", headers=headers
    ).status_code == 403
    assert client.post(
        f"/api/expenses/{theirs.id}/transition",
        headers=headers, json={"transition_code": "APPROVE"},
    ).status_code == 403


def test_a_user_with_no_assignment_sees_only_their_own(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = make_user("unplaced", ("MANAGER",))
    seeded.add(Employee(
        employee_code="EMP-EXX", user_id=user.id,
        first_name="Unplaced", last_name="Manager",
        email="unplaced.exp@example.local",
        business_unit_id=unit(seeded, "DEPARTMENT_1").id,
    ))
    seeded.commit()
    own = make_claim(seeded, user)

    rows = rows_for(client, login_headers("unplaced"))
    assert len(rows) == 1
    assert rows[0]["id"] == own.id


# ===========================================================================
# RBAC
# ===========================================================================


def test_expense_endpoints_need_authentication(
    client: TestClient, seeded: Session
) -> None:
    assert client.get("/api/expenses").status_code == 401
    assert client.get("/api/expenses/categories").status_code == 401
    assert client.get("/api/expenses/dashboard").status_code == 401


def test_a_role_without_the_application_is_refused_everything(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "noapp", "APPLICATION_ADMIN", "COMPANY_1")
    headers = login_headers("noapp")

    assert client.get("/api/expenses", headers=headers).status_code == 403
    assert client.get("/api/expenses/categories", headers=headers).status_code == 403
    assert client.post("/api/expenses", headers=headers, json={}).status_code == 403


@pytest.mark.parametrize("role_code", ["SUPER_ADMIN", "HR", "MANAGER", "EMPLOYEE"])
def test_every_role_with_the_application_can_open_it(
    client: TestClient, seeded: Session, make_user, login_headers, role_code: str
) -> None:
    """Expenses are self-service: an ordinary employee must get in."""
    staff(seeded, make_user, "person", role_code, "COMPANY_1")

    assert client.get(
        "/api/expenses", headers=login_headers("person")
    ).status_code == 200


def test_an_employee_is_not_offered_the_management_screens(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "selfserve", "EMPLOYEE", "DEPARTMENT_1")

    response = client.get(
        "/api/access/applications/EXPENSE_MANAGEMENT/screens",
        headers=login_headers("selfserve"),
    )
    assert response.status_code == 200
    assert {s["code"] for s in response.json()} == {"MY_EXPENSES"}


def test_a_manager_is_offered_the_approval_screen(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "teamlead", "MANAGER", "BRANCH_1")

    response = client.get(
        "/api/access/applications/EXPENSE_MANAGEMENT/screens",
        headers=login_headers("teamlead"),
    )
    codes_found = {s["code"] for s in response.json()}
    assert {"EXPENSE_APPROVAL", "EXPENSE_DASHBOARD", "MY_EXPENSES"} <= codes_found


# ===========================================================================
# Receipts
# ===========================================================================


def test_a_valid_receipt_is_accepted_and_linked(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "uploader", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, user)

    response = client.post(
        f"/api/expenses/{claim.id}/attachments",
        headers=login_headers("uploader"),
        files={"upload": ("receipt.png", TINY_PNG, "image/png")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["file_name"] == "receipt.png"
    assert body["content_type"] == "image/png"
    assert body["file_size"] == len(TINY_PNG)
    # The metadata is linked to the claim, and the stored name never leaves
    # the server.
    assert "stored_name" not in body

    detail = client.get(
        f"/api/expenses/{claim.id}", headers=login_headers("uploader")
    ).json()
    assert len(detail["attachments"]) == 1


def test_an_unsupported_file_type_is_rejected(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "badtype", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, user)

    response = client.post(
        f"/api/expenses/{claim.id}/attachments",
        headers=login_headers("badtype"),
        files={"upload": ("payload.exe", b"MZ\x90\x00", "application/x-msdownload")},
    )

    assert response.status_code == 400
    assert "JPEG" in response.json()["detail"]
    assert seeded.scalar(select(func.count()).select_from(ExpenseAttachment)
                         .where(ExpenseAttachment.expense_id == claim.id)) == 0


def test_an_oversized_file_is_rejected(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "toobig", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, user)
    oversized = b"\x00" * (expense_service.MAX_RECEIPT_BYTES + 1)

    response = client.post(
        f"/api/expenses/{claim.id}/attachments",
        headers=login_headers("toobig"),
        files={"upload": ("huge.pdf", oversized, "application/pdf")},
    )

    assert response.status_code == 400
    assert "too large" in response.json()["detail"]


def test_an_empty_file_is_rejected(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "emptyfile", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, user)

    response = client.post(
        f"/api/expenses/{claim.id}/attachments",
        headers=login_headers("emptyfile"),
        files={"upload": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400


def test_a_traversal_filename_never_reaches_the_filesystem(
    seeded: Session, make_user
) -> None:
    """
    The reason `file_name` and `stored_name` are two different columns.

    The name the browser sent is kept for display and stripped to its last
    segment; the name on disk is generated here and contains nothing a caller
    supplied.
    """
    user = staff(seeded, make_user, "traversal", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, user)

    attachment = expense_service.add_attachment(
        seeded, user, claim.id,
        file_name="../../../../etc/passwd",
        content_type="image/png",
        payload=TINY_PNG,
    )

    assert "/" not in attachment.stored_name
    assert ".." not in attachment.stored_name
    assert attachment.stored_name.endswith(".png")
    assert "/" not in attachment.file_name and ".." not in attachment.file_name
    # The file really is inside the receipt directory.
    written = expense_service._receipt_path(attachment.stored_name)
    assert written.is_relative_to(expense_service.RECEIPT_ROOT.resolve())
    assert written.is_file()
    written.unlink(missing_ok=True)


def test_a_receipt_cannot_be_attached_to_somebody_elses_claim(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    worker = staff(seeded, make_user, "victim", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, worker)
    staff(seeded, make_user, "intruder", "MANAGER", "BRANCH_1")

    response = client.post(
        f"/api/expenses/{claim.id}/attachments",
        headers=login_headers("intruder"),
        files={"upload": ("receipt.png", TINY_PNG, "image/png")},
    )
    assert response.status_code == 403


def test_a_receipt_cannot_be_attached_once_submitted(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """Attaching to a claim under review would change what is being reviewed."""
    user = staff(seeded, make_user, "latefile", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, user)
    expense_service.execute_transition(seeded, user, claim.id, "SUBMIT", None)

    response = client.post(
        f"/api/expenses/{claim.id}/attachments",
        headers=login_headers("latefile"),
        files={"upload": ("receipt.png", TINY_PNG, "image/png")},
    )
    assert response.status_code == 400


def test_a_receipt_downloads_for_someone_who_may_see_the_claim(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    worker = staff(seeded, make_user, "downloader", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, worker)
    attachment = expense_service.add_attachment(
        seeded, worker, claim.id,
        file_name="receipt.png", content_type="image/png", payload=TINY_PNG,
    )
    expense_service.execute_transition(seeded, worker, claim.id, "SUBMIT", None)
    staff(seeded, make_user, "reviewer", "MANAGER", "BRANCH_1", with_employee=False)

    response = client.get(
        f"/api/expenses/attachments/{attachment.id}/download",
        headers=login_headers("reviewer"),
    )

    assert response.status_code == 200
    assert response.content == TINY_PNG
    assert response.headers["content-type"] == "image/png"
    expense_service._receipt_path(attachment.stored_name).unlink(missing_ok=True)


def test_a_receipt_is_not_downloadable_out_of_scope(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """The scope check happens through the parent claim, not the file."""
    outsider = staff(seeded, make_user, "faraway", "EMPLOYEE", "DEPARTMENT_5")
    claim = make_claim(seeded, outsider)
    attachment = expense_service.add_attachment(
        seeded, outsider, claim.id,
        file_name="private.pdf", content_type="application/pdf", payload=b"%PDF-1.4",
    )
    staff(seeded, make_user, "prying", "MANAGER", "BRANCH_1", with_employee=False)

    response = client.get(
        f"/api/expenses/attachments/{attachment.id}/download",
        headers=login_headers("prying"),
    )

    assert response.status_code == 403
    expense_service._receipt_path(attachment.stored_name).unlink(missing_ok=True)


def test_an_owner_can_remove_a_receipt_from_a_draft(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "remover", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, user)
    attachment = expense_service.add_attachment(
        seeded, user, claim.id,
        file_name="receipt.png", content_type="image/png", payload=TINY_PNG,
    )
    path = expense_service._receipt_path(attachment.stored_name)

    response = client.delete(
        f"/api/expenses/attachments/{attachment.id}",
        headers=login_headers("remover"),
    )

    assert response.status_code == 204
    assert seeded.get(ExpenseAttachment, attachment.id) is None
    # The bytes go too, not just the row.
    assert not path.exists()


def test_the_attachment_cap_is_enforced(seeded: Session, make_user) -> None:
    user = staff(seeded, make_user, "hoarder", "EMPLOYEE", "DEPARTMENT_1")
    claim = make_claim(seeded, user)
    written = []

    for index in range(expense_service.MAX_ATTACHMENTS_PER_EXPENSE):
        attachment = expense_service.add_attachment(
            seeded, user, claim.id,
            file_name=f"receipt{index}.png", content_type="image/png",
            payload=TINY_PNG,
        )
        written.append(expense_service._receipt_path(attachment.stored_name))

    with pytest.raises(ExpenseError):
        expense_service.add_attachment(
            seeded, user, claim.id,
            file_name="one-too-many.png", content_type="image/png", payload=TINY_PNG,
        )

    for path in written:
        path.unlink(missing_ok=True)


# ===========================================================================
# Dashboard
# ===========================================================================


def test_dashboard_totals_agree_with_the_list(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "dashadmin", "SUPER_ADMIN", "HQ", with_employee=False)
    headers = login_headers("dashadmin")

    summary = client.get("/api/expenses/dashboard", headers=headers).json()
    listed = client.get(
        "/api/expenses", headers=headers, params={"page_size": 1}
    ).json()

    assert summary["total_claims"] == listed["total"]
    # The five buckets partition the whole.
    assert (
        summary["draft"] + summary["submitted"] + summary["approved"]
        + summary["rejected"] + summary["cancelled"]
    ) == summary["total_claims"]
    assert sum(s["value"] for s in summary["by_status"]) == summary["total_claims"]
    assert Decimal(str(summary["approved_amount"])) <= Decimal(
        str(summary["total_amount"])
    )


def test_every_total_is_reported_with_its_currency(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """
    Adding 100 USD to 100 EUR gives 200 of nothing, so no figure is ever sent
    without the currency it is a figure in.
    """
    user = staff(seeded, make_user, "mixer", "EMPLOYEE", "DEPARTMENT_1")
    make_claim(seeded, user, amount="100.00", currency="USD",
               when=date.today())
    make_claim(seeded, user, amount="100.00", currency="USD",
               when=date.today() - timedelta(days=1))
    make_claim(seeded, user, amount="70.00", currency="EUR",
               when=date.today() - timedelta(days=2))

    summary = client.get(
        "/api/expenses/dashboard", headers=login_headers("mixer")
    ).json()

    # The reporting currency is the one most claims are in, and the totals are
    # that currency's - not a meaningless sum across both.
    assert summary["currency"] == "USD"
    assert Decimal(str(summary["total_amount"])) == Decimal("200.00")
    # The other currency is still reported, separately and honestly.
    by_currency = {c["currency"]: Decimal(str(c["total"]))
                   for c in summary["totals_by_currency"]}
    assert by_currency == {"USD": Decimal("200.00"), "EUR": Decimal("70.00")}
    assert summary["total_claims"] == 3


def test_the_dashboard_respects_business_unit_scope(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "d_hq", "SUPER_ADMIN", "HQ", with_employee=False)
    staff(seeded, make_user, "d_br", "MANAGER", "BRANCH_1", with_employee=False)

    hq = client.get("/api/expenses/dashboard", headers=login_headers("d_hq")).json()
    br = client.get("/api/expenses/dashboard", headers=login_headers("d_br")).json()

    assert br["total_claims"] < hq["total_claims"]
    assert Decimal(str(br["total_amount"])) < Decimal(str(hq["total_amount"]))


def test_an_employees_dashboard_shows_only_their_own(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "solo", "EMPLOYEE", "DEPARTMENT_1")
    make_claim(seeded, user, amount="30.00", when=date.today())
    make_claim(seeded, user, amount="20.00", when=date.today() - timedelta(days=1))

    summary = client.get(
        "/api/expenses/dashboard", headers=login_headers("solo")
    ).json()

    assert summary["total_claims"] == 2
    assert Decimal(str(summary["total_amount"])) == Decimal("50.00")
    assert summary["draft"] == 2


def test_category_aggregation_is_correct(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "categoriser", "EMPLOYEE", "DEPARTMENT_1")
    make_claim(seeded, user, amount="100.00", category_code="TRAVEL",
               when=date.today())
    make_claim(seeded, user, amount="50.00", category_code="TRAVEL",
               when=date.today() - timedelta(days=1))
    make_claim(seeded, user, amount="20.00", category_code="MEALS",
               when=date.today() - timedelta(days=2))

    summary = client.get(
        "/api/expenses/dashboard", headers=login_headers("categoriser")
    ).json()
    by_category = {row["name"]: row["value"] for row in summary["by_category"]}

    assert by_category == {"Travel": 150, "Meals": 20}


def test_status_aggregation_uses_metadata_state_names(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    manager = staff(seeded, make_user, "statusboss", "MANAGER", "BRANCH_1")
    user = staff(seeded, make_user, "statususer", "EMPLOYEE", "DEPARTMENT_1")
    make_claim(seeded, user, amount="10.00", when=date.today())
    approved = make_claim(seeded, user, amount="90.00",
                          when=date.today() - timedelta(days=1))
    expense_service.execute_transition(seeded, user, approved.id, "SUBMIT", None)
    expense_service.execute_transition(seeded, manager, approved.id, "APPROVE", None)

    summary = client.get(
        "/api/expenses/dashboard", headers=login_headers("statususer")
    ).json()
    by_status = {row["name"]: row["value"] for row in summary["by_status"]}

    assert by_status == {
        "Draft": 1, "Submitted": 0, "Approved": 1, "Rejected": 0, "Cancelled": 0,
    }
    assert summary["approved"] == 1
    assert Decimal(str(summary["approved_amount"])) == Decimal("90.00")


def test_monthly_aggregation_groups_and_orders_by_expense_date(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "monther", "EMPLOYEE", "DEPARTMENT_1")
    make_claim(seeded, user, amount="30.00", when=date(2027, 3, 2))
    make_claim(seeded, user, amount="10.00", when=date(2027, 1, 11))
    make_claim(seeded, user, amount="15.00", when=date(2027, 1, 25))

    summary = client.get(
        "/api/expenses/dashboard", headers=login_headers("monther")
    ).json()

    assert summary["by_month"] == [
        {"name": "2027-01", "value": 25},
        {"name": "2027-03", "value": 30},
    ]


def test_expense_widgets_are_served_with_live_scoped_values(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """The metadata chain end to end: shape stays configuration, numbers live."""
    staff(seeded, make_user, "w_hq", "SUPER_ADMIN", "HQ", with_employee=False)
    staff(seeded, make_user, "w_br", "MANAGER", "BRANCH_1", with_employee=False)

    hq = client.get(
        "/api/access/dashboards/EXPENSE_OVERVIEW/data", headers=login_headers("w_hq")
    )
    br = client.get(
        "/api/access/dashboards/EXPENSE_OVERVIEW/data", headers=login_headers("w_br")
    )
    assert hq.status_code == 200, hq.text
    assert br.status_code == 200, br.text

    hq_data, br_data = hq.json(), br.json()
    assert hq_data["CLAIMS_TOTAL"]["value"] > br_data["CLAIMS_TOTAL"]["value"]
    assert hq_data["CLAIM_VALUE"]["value"] > br_data["CLAIM_VALUE"]["value"]
    assert set(hq_data["BY_CATEGORY"]) == {"categories", "series"}
    assert set(hq_data["BY_MONTH"]) == {"categories", "series"}
    assert "series" in hq_data["BY_STATUS"]
    assert all(s["value"] > 0 for s in hq_data["BY_STATUS"]["series"])
    # The money tile says what currency it is in.
    assert "USD" in hq_data["CLAIM_VALUE"]["caption"]


def test_an_employee_cannot_reach_the_expense_dashboard_metadata(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "nodash", "EMPLOYEE", "DEPARTMENT_1")
    headers = login_headers("nodash")

    assert client.get(
        "/api/access/screens/EXPENSE_DASHBOARD/dashboards", headers=headers
    ).status_code == 404
    assert client.get(
        "/api/access/dashboards/EXPENSE_OVERVIEW/data", headers=headers
    ).status_code == 404


# ===========================================================================
# Filters and the seed
# ===========================================================================


def test_the_pending_filter_is_derived_from_metadata(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "queueboss", "MANAGER", "BRANCH_1", with_employee=False)

    rows = rows_for(client, login_headers("queueboss"), pending="true")

    assert len(rows) > 0
    assert {r["state_code"] for r in rows} == {"SUBMITTED"}
    assert all(r["is_final"] is False for r in rows)
    assert all(r["is_editable"] is False for r in rows)


def test_the_category_filter_narrows_without_escaping_scope(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "catfilter", "MANAGER", "BRANCH_1", with_employee=False)
    travel = category(seeded, "TRAVEL")

    rows = rows_for(
        client, login_headers("catfilter"), category_id=travel.id, pending="false"
    )

    assert_scoped_to(rows, "BRANCH_1")
    assert all(r["category"]["name"] == "Travel" for r in rows)


def test_the_mine_filter_narrows_to_the_caller(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    manager = staff(seeded, make_user, "mineboss", "MANAGER", "BRANCH_1")
    own = make_claim(seeded, manager)
    headers = login_headers("mineboss")

    everything = rows_for(client, headers)
    mine = rows_for(client, headers, mine="true")

    assert len(mine) == 1 and mine[0]["id"] == own.id
    assert len(everything) > len(mine)


def test_the_seed_is_idempotent(seeded: Session) -> None:
    from app.metadata.seed import seed_all

    changed = seed_all(seeded)

    assert changed["expense_categories"] == 0
    assert changed["expenses"] == 0
    assert changed["expense_history"] == 0
    assert changed["workflows"] == 0
    assert changed["workflow_transitions"] == 0
