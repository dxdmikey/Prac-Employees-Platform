"""
Tests for Attendance (Stage 10).

Three things are being proven:

  1. the clock rules work - a day cannot be checked out twice, checked out
     before it was checked in, or checked in twice,
  2. **the stored duration always matches its own timestamps**, because
     worked_minutes is derived but persisted and a drift there would poison
     every total that sums it,
  3. **every read is scoped**. Your own attendance always; somebody else's
     only with the APPROVE permission and business-unit scope.

The seeded fixtures are generated rather than listed, so the expectations
below are computed from the same generator the seed uses. That keeps the tests
honest when the fixture changes, and - just as importantly - lets them survive
a database where somebody has been clicking around in the browser.
"""

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.metadata import seed
from app.models.attendance import HALF_DAY_THRESHOLD_MINUTES, Attendance
from app.models.business_unit import BusinessUnit
from app.models.employee import Employee
from app.models.user import User
from app.services import attendance_service
from app.services.attendance_service import (
    AttendanceError,
    AttendanceNotVisible,
)

# ---------------------------------------------------------------------------
# Expectations derived from the seed, not copied from it
# ---------------------------------------------------------------------------

_UNIT_PARENT = {s.code: s.parent_code for s in seed.BUSINESS_UNITS}
_EMPLOYEE_UNIT = {s.code: s.business_unit_code for s in seed.EMPLOYEES}
_EMPLOYEE_NAME = {s.code: f"{s.first_name} {s.last_name}" for s in seed.EMPLOYEES}
_UNIT_NAME = {s.code: s.name for s in seed.BUSINESS_UNITS}


def units_under(unit_code: str) -> set[str]:
    found = {unit_code}
    while True:
        grown = found | {u for u, parent in _UNIT_PARENT.items() if parent in found}
        if grown == found:
            return found
        found = grown


def unit_names_under(unit_code: str) -> set[str]:
    return {_UNIT_NAME[code] for code in units_under(unit_code)}


def seeded_attendance_under(unit_code: str) -> int:
    """How many generated attendance rows sit at or below this unit."""
    units = units_under(unit_code)
    return sum(
        1
        for row in seed.build_attendance_rows(attendance_service.today())
        if _EMPLOYEE_UNIT[row.employee_code] in units
    )


def assert_scoped_to(rows: list[dict], unit_code: str) -> None:
    """
    Every visible row belongs to a unit at or below `unit_code`.

    Structural rather than a fixed expected list: these tests run against the
    developer's real database, where the fixtures are the floor and not the
    ceiling. What can never happen, however much real data is present, is a
    row from outside the caller's scope appearing here.
    """
    allowed = unit_names_under(unit_code)
    leaked = {r["business_unit"]["name"] for r in rows} - allowed
    assert not leaked, f"rows leaked from outside {unit_code}: {sorted(leaked)}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def unit(db: Session, code: str) -> BusinessUnit:
    return db.scalar(select(BusinessUnit).where(BusinessUnit.code == code))


_counter = {"n": 0}


def staff(
    db: Session, make_user, username: str, role: str, unit_code: str,
    *, with_employee: bool = True,
) -> User:
    """A user with a role (WHAT), a business unit (WHERE) and usually an employee."""
    user = make_user(username, (role,))
    user.business_units.append(unit(db, unit_code))
    db.commit()

    if with_employee:
        _counter["n"] += 1
        n = _counter["n"]
        db.add(Employee(
            employee_code=f"EMP-AT{n:03d}",
            user_id=user.id,
            first_name=username.capitalize(),
            last_name="Attendtest",
            email=f"{username}.attendtest{n}@example.local",
            business_unit_id=unit(db, unit_code).id,
        ))
        db.commit()
    return user


def rows_for(client: TestClient, headers, **params) -> list[dict]:
    params.setdefault("page_size", 100)
    response = client.get("/api/attendance", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


# ===========================================================================
# The duration calculation
# ===========================================================================


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("09:00", "17:00", 480),
        ("09:00", "09:01", 1),
        ("08:45", "13:15", 270),
        ("09:00", "09:00", 0),
    ],
)
def test_worked_minutes_is_whole_minutes_between_the_two_times(
    start: str, end: str, expected: int
) -> None:
    day = date(2026, 9, 14)
    check_in = datetime.fromisoformat(f"{day}T{start}:00").astimezone()
    check_out = datetime.fromisoformat(f"{day}T{end}:00").astimezone()

    assert attendance_service.calculate_worked_minutes(check_in, check_out) == expected


def test_an_unfinished_day_has_no_duration() -> None:
    check_in = datetime.fromisoformat("2026-09-14T09:00:00").astimezone()
    assert attendance_service.calculate_worked_minutes(check_in, None) is None
    assert attendance_service.calculate_worked_minutes(None, None) is None


def test_a_checkout_before_its_checkin_is_refused_rather_than_negative() -> None:
    """
    A negative duration is not a small error to tolerate. It would mean the two
    timestamps are not what they claim, and storing it would poison every total.
    """
    check_in = datetime.fromisoformat("2026-09-14T17:00:00").astimezone()
    check_out = datetime.fromisoformat("2026-09-14T09:00:00").astimezone()

    with pytest.raises(AttendanceError):
        attendance_service.calculate_worked_minutes(check_in, check_out)


@pytest.mark.parametrize(
    ("check_in_at", "check_out_at", "expected"),
    [
        (None, None, "ABSENT"),
        ("09:00", None, "INCOMPLETE"),
        ("09:00", "17:00", "PRESENT"),
        ("09:00", "12:00", "HALF_DAY"),
    ],
)
def test_status_is_derived_from_the_timestamps(
    check_in_at: str | None, check_out_at: str | None, expected: str
) -> None:
    day = date(2026, 9, 14)
    check_in = (
        None if check_in_at is None
        else datetime.fromisoformat(f"{day}T{check_in_at}:00").astimezone()
    )
    check_out = (
        None if check_out_at is None
        else datetime.fromisoformat(f"{day}T{check_out_at}:00").astimezone()
    )
    minutes = attendance_service.calculate_worked_minutes(check_in, check_out)

    assert attendance_service.derive_status(check_in, check_out, minutes) == expected


def test_the_half_day_boundary_is_inclusive() -> None:
    """Exactly the threshold counts as a full day, one minute under does not."""
    day = date(2026, 9, 14)
    check_in = datetime.fromisoformat(f"{day}T09:00:00").astimezone()

    at_threshold = check_in + timedelta(minutes=HALF_DAY_THRESHOLD_MINUTES)
    just_under = check_in + timedelta(minutes=HALF_DAY_THRESHOLD_MINUTES - 1)

    assert attendance_service.derive_status(
        check_in, at_threshold, HALF_DAY_THRESHOLD_MINUTES
    ) == "PRESENT"
    assert attendance_service.derive_status(
        check_in, just_under, HALF_DAY_THRESHOLD_MINUTES - 1
    ) == "HALF_DAY"


# ===========================================================================
# Check in / check out
# ===========================================================================


def test_check_in_creates_todays_record(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "arriver", "EMPLOYEE", "DEPARTMENT_1")

    response = client.post("/api/attendance/check-in", headers=login_headers("arriver"))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["attendance_date"] == attendance_service.today().isoformat()
    assert body["check_in"] is not None
    assert body["check_out"] is None
    assert body["attendance_status"] == "INCOMPLETE"
    assert body["is_open"] is True


def test_a_second_check_in_is_refused(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "keen", "EMPLOYEE", "DEPARTMENT_1")
    headers = login_headers("keen")
    assert client.post("/api/attendance/check-in", headers=headers).status_code == 201

    second = client.post("/api/attendance/check-in", headers=headers)

    assert second.status_code == 400
    assert "already checked in" in second.json()["detail"]


def test_check_out_records_the_duration(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "worker", "EMPLOYEE", "DEPARTMENT_1")
    record = attendance_service.check_in(seeded, user)
    # Wind the check-in back so the day has a measurable length.
    record.check_in = record.check_in - timedelta(hours=8)
    seeded.commit()

    response = client.post("/api/attendance/check-out", headers=login_headers("worker"))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["check_out"] is not None
    assert body["worked_minutes"] >= 8 * 60
    assert body["attendance_status"] == "PRESENT"
    assert body["is_open"] is False


def test_check_out_without_a_check_in_is_refused(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "absent", "EMPLOYEE", "DEPARTMENT_1")

    response = client.post("/api/attendance/check-out", headers=login_headers("absent"))

    assert response.status_code == 400
    assert "not checked in" in response.json()["detail"]


def test_a_second_check_out_is_refused(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "leaver", "EMPLOYEE", "DEPARTMENT_1")
    attendance_service.check_in(seeded, user)
    headers = login_headers("leaver")
    assert client.post("/api/attendance/check-out", headers=headers).status_code == 200

    second = client.post("/api/attendance/check-out", headers=headers)

    assert second.status_code == 400
    assert "already checked out" in second.json()["detail"]


def test_only_one_record_exists_per_employee_per_day(
    seeded: Session, make_user
) -> None:
    """The database enforces it, not just the service."""
    from sqlalchemy.exc import IntegrityError

    user = staff(seeded, make_user, "dup", "EMPLOYEE", "DEPARTMENT_1")
    employee = attendance_service.get_own_employee(seeded, user)
    attendance_service.check_in(seeded, user)

    seeded.add(Attendance(
        employee_id=employee.id,
        attendance_date=attendance_service.today(),
        attendance_status="PRESENT",
    ))
    with pytest.raises(IntegrityError):
        seeded.commit()
    seeded.rollback()


def test_today_endpoint_drives_the_buttons(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """
    The two booleans are the backend's answer, and the screen renders them
    rather than inspecting timestamps itself.
    """
    staff(seeded, make_user, "today1", "EMPLOYEE", "DEPARTMENT_1")
    headers = login_headers("today1")

    before = client.get("/api/attendance/today", headers=headers).json()
    assert before["can_check_in"] is True
    assert before["can_check_out"] is False
    assert before["attendance"] is None

    client.post("/api/attendance/check-in", headers=headers)
    mid = client.get("/api/attendance/today", headers=headers).json()
    assert mid["can_check_in"] is False
    assert mid["can_check_out"] is True

    client.post("/api/attendance/check-out", headers=headers)
    after = client.get("/api/attendance/today", headers=headers).json()
    assert after["can_check_in"] is False
    assert after["can_check_out"] is False


def test_a_user_with_no_employee_record_cannot_check_in(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """And no employee record is invented for them on the way past."""
    before = seeded.scalar(select(func.count()).select_from(Employee))
    staff(seeded, make_user, "nobody", "EMPLOYEE", "DEPARTMENT_1", with_employee=False)

    response = client.post("/api/attendance/check-in", headers=login_headers("nobody"))

    assert response.status_code == 409
    assert "employee record" in response.json()["detail"]
    assert seeded.scalar(select(func.count()).select_from(Employee)) == before


def test_check_in_reuses_a_day_already_marked_absent(
    seeded: Session, make_user
) -> None:
    """Somebody marked absent who then turns up gets one row, not two."""
    user = staff(seeded, make_user, "latecomer", "EMPLOYEE", "DEPARTMENT_1")
    employee = attendance_service.get_own_employee(seeded, user)
    seeded.add(Attendance(
        employee_id=employee.id,
        attendance_date=attendance_service.today(),
        attendance_status="ABSENT",
    ))
    seeded.commit()

    record = attendance_service.check_in(seeded, user)

    assert record.attendance_status == "INCOMPLETE"
    assert seeded.scalar(
        select(func.count()).select_from(Attendance)
        .where(Attendance.employee_id == employee.id,
               Attendance.attendance_date == attendance_service.today())
    ) == 1


# ===========================================================================
# The stored duration never drifts
# ===========================================================================


def test_every_seeded_completed_day_matches_its_own_timestamps(
    seeded: Session,
) -> None:
    """
    worked_minutes is derived but persisted, so this is the test that keeps
    that trade-off safe. It checks the fixtures, which are the largest body of
    attendance in the database.
    """
    mismatches = [
        record.id
        for record in seeded.scalars(
            select(Attendance).where(Attendance.check_out.is_not(None)).limit(500)
        )
        if record.worked_minutes
        != attendance_service.calculate_worked_minutes(
            record.check_in, record.check_out
        )
    ]
    assert mismatches == []


def test_an_open_day_stores_no_duration(seeded: Session) -> None:
    open_days = seeded.scalars(
        select(Attendance)
        .where(Attendance.check_in.is_not(None), Attendance.check_out.is_(None))
        .limit(50)
    )
    for record in open_days:
        assert record.worked_minutes is None
        assert record.attendance_status == "INCOMPLETE"


# ===========================================================================
# Visibility and business-unit scope
# ===========================================================================


def test_an_employee_sees_only_their_own_attendance(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """
    The sharpest version of the rule: two colleagues in the *same* department.
    Scope alone is not enough, because an EMPLOYEE has no APPROVE permission.
    """
    colleague = staff(seeded, make_user, "colleague", "EMPLOYEE", "DEPARTMENT_1")
    theirs = attendance_service.check_in(seeded, colleague)
    staff(seeded, make_user, "nosy", "EMPLOYEE", "DEPARTMENT_1")
    headers = login_headers("nosy")

    assert rows_for(client, headers) == []
    assert client.get(
        f"/api/attendance/{theirs.id}", headers=headers
    ).status_code == 403


def test_a_manager_sees_their_unit_and_its_descendants(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "branchboss", "MANAGER", "BRANCH_1", with_employee=False)

    rows = rows_for(client, login_headers("branchboss"))
    names = {r["employee"]["name"] for r in rows}

    assert_scoped_to(rows, "BRANCH_1")
    assert _EMPLOYEE_NAME["EMP-005"] in names      # Department 1
    assert _EMPLOYEE_NAME["EMP-008"] in names      # Department 2
    assert _EMPLOYEE_NAME["EMP-012"] not in names  # Branch 2
    assert _EMPLOYEE_NAME["EMP-019"] not in names  # Company 2


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


def test_a_user_with_no_assignment_sees_only_their_own(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """No assignment means nothing, never everything - even for an approver."""
    user = make_user("unplaced", ("MANAGER",))
    seeded.add(Employee(
        employee_code="EMP-ATX",
        user_id=user.id,
        first_name="Unplaced",
        last_name="Manager",
        email="unplaced.attend@example.local",
        business_unit_id=unit(seeded, "DEPARTMENT_1").id,
    ))
    seeded.commit()
    attendance_service.check_in(seeded, user)

    rows = rows_for(client, login_headers("unplaced"))
    assert len(rows) == 1
    assert rows[0]["employee"]["name"] == "Unplaced Manager"


def test_an_out_of_scope_record_cannot_be_reached_by_id(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    outsider = staff(seeded, make_user, "far", "EMPLOYEE", "DEPARTMENT_5")
    theirs = attendance_service.check_in(seeded, outsider)
    staff(seeded, make_user, "near", "MANAGER", "BRANCH_1", with_employee=False)

    assert client.get(
        f"/api/attendance/{theirs.id}", headers=login_headers("near")
    ).status_code == 403


def test_the_mine_filter_narrows_to_the_caller(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    manager = staff(seeded, make_user, "mineboss", "MANAGER", "BRANCH_1")
    attendance_service.check_in(seeded, manager)
    headers = login_headers("mineboss")

    everything = rows_for(client, headers)
    mine = rows_for(client, headers, mine="true")

    assert len(mine) == 1
    assert len(everything) > len(mine)


def test_the_open_only_filter_finds_missing_checkouts(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """The query a manager actually runs: who checked in and never checked out."""
    staff(seeded, make_user, "chaser", "MANAGER", "BRANCH_1", with_employee=False)

    rows = rows_for(client, login_headers("chaser"), open_only="true")

    assert len(rows) > 0
    assert all(r["check_in"] is not None for r in rows)
    assert all(r["check_out"] is None for r in rows)
    assert all(r["is_open"] is True for r in rows)


def test_an_unknown_status_filter_is_rejected(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "filterer", "MANAGER", "BRANCH_1", with_employee=False)

    response = client.get(
        "/api/attendance",
        headers=login_headers("filterer"),
        params={"attendance_status": "NAPPING"},
    )
    assert response.status_code == 400


def test_a_date_range_filter_narrows_without_escaping_scope(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "ranger", "MANAGER", "BRANCH_1", with_employee=False)
    today = attendance_service.today()

    rows = rows_for(
        client, login_headers("ranger"),
        date_from=(today - timedelta(days=3)).isoformat(),
        date_to=today.isoformat(),
    )
    assert_scoped_to(rows, "BRANCH_1")
    assert all(
        date.fromisoformat(r["attendance_date"]) >= today - timedelta(days=3)
        for r in rows
    )


# ===========================================================================
# RBAC
# ===========================================================================


def test_attendance_endpoints_need_authentication(
    client: TestClient, seeded: Session
) -> None:
    assert client.get("/api/attendance").status_code == 401
    assert client.get("/api/attendance/today").status_code == 401
    assert client.post("/api/attendance/check-in").status_code == 401


def test_a_role_without_the_application_is_refused_everything(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """APPLICATION_ADMIN is seeded with no applications, so RBAC runs first."""
    staff(seeded, make_user, "noapp", "APPLICATION_ADMIN", "COMPANY_1")
    headers = login_headers("noapp")

    assert client.get("/api/attendance", headers=headers).status_code == 403
    assert client.get("/api/attendance/today", headers=headers).status_code == 403
    assert client.post("/api/attendance/check-in", headers=headers).status_code == 403


@pytest.mark.parametrize("role_code", ["SUPER_ADMIN", "HR", "MANAGER", "EMPLOYEE"])
def test_every_role_with_the_application_can_open_it(
    client: TestClient, seeded: Session, make_user, login_headers, role_code: str
) -> None:
    """Attendance is self-service: an ordinary employee must get in."""
    staff(seeded, make_user, "person", role_code, "COMPANY_1")

    assert client.get(
        "/api/attendance/today", headers=login_headers("person")
    ).status_code == 200


def test_an_employee_is_not_offered_the_management_screens(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "selfserve", "EMPLOYEE", "DEPARTMENT_1")

    response = client.get(
        "/api/access/applications/ATTENDANCE_TIMESHEET/screens",
        headers=login_headers("selfserve"),
    )
    assert response.status_code == 200
    assert {s["code"] for s in response.json()} == {"MY_ATTENDANCE", "TIMESHEET"}


def test_a_manager_is_offered_the_management_screens(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "teamlead", "MANAGER", "BRANCH_1")

    response = client.get(
        "/api/access/applications/ATTENDANCE_TIMESHEET/screens",
        headers=login_headers("teamlead"),
    )
    codes = {s["code"] for s in response.json()}
    assert {"TEAM_ATTENDANCE", "TIMESHEET_APPROVAL", "ATTENDANCE_DASHBOARD"} <= codes


# ===========================================================================
# Corrections
# ===========================================================================


def test_an_administrator_can_correct_a_day(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """HR holds EDIT, so the correction endpoint is theirs."""
    worker = staff(seeded, make_user, "forgetful", "EMPLOYEE", "DEPARTMENT_1")
    record = attendance_service.check_in(seeded, worker)
    staff(seeded, make_user, "hradmin", "HR", "COMPANY_1", with_employee=False)

    check_out_at = record.check_in + timedelta(hours=8)
    response = client.patch(
        f"/api/attendance/{record.id}",
        headers=login_headers("hradmin"),
        json={"check_out": check_out_at.isoformat(), "remarks": "Forgot to check out."},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["worked_minutes"] == 480
    assert body["attendance_status"] == "PRESENT"
    assert body["remarks"] == "Forgot to check out."


def test_a_manager_without_edit_cannot_correct(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """
    MANAGER holds VIEW, APPROVE and EXPORT - not EDIT. The refusal comes from
    the existing require_permission dependency, not from a role name.
    """
    worker = staff(seeded, make_user, "employee2", "EMPLOYEE", "DEPARTMENT_1")
    record = attendance_service.check_in(seeded, worker)
    staff(seeded, make_user, "lead2", "MANAGER", "BRANCH_1", with_employee=False)

    response = client.patch(
        f"/api/attendance/{record.id}",
        headers=login_headers("lead2"),
        json={"remarks": "Nice try."},
    )
    assert response.status_code == 403


def test_a_correction_cannot_reach_outside_the_scope(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """EDIT is not a skeleton key - scope is still checked in the service."""
    outsider = staff(seeded, make_user, "faraway", "EMPLOYEE", "DEPARTMENT_5")
    record = attendance_service.check_in(seeded, outsider)
    staff(seeded, make_user, "hrlocal", "HR", "BRANCH_1", with_employee=False)

    response = client.patch(
        f"/api/attendance/{record.id}",
        headers=login_headers("hrlocal"),
        json={"remarks": "Out of reach."},
    )
    assert response.status_code == 403


def test_a_correction_recalculates_rather_than_trusting(
    seeded: Session, make_user
) -> None:
    """A corrected day cannot end up claiming a duration its times do not support."""
    worker = staff(seeded, make_user, "recalc", "EMPLOYEE", "DEPARTMENT_1")
    admin = staff(seeded, make_user, "recalcadmin", "HR", "COMPANY_1",
                  with_employee=False)
    record = attendance_service.check_in(seeded, worker)

    updated = attendance_service.correct_record(
        seeded, admin, record.id,
        {"check_out": record.check_in + timedelta(minutes=200)},
    )

    assert updated.worked_minutes == 200
    assert updated.attendance_status == "HALF_DAY"


def test_a_correction_may_set_a_status_no_timestamp_could_explain(
    seeded: Session, make_user
) -> None:
    """ON_LEAVE is a fact about approved leave, not about two timestamps."""
    worker = staff(seeded, make_user, "away", "EMPLOYEE", "DEPARTMENT_1")
    admin = staff(seeded, make_user, "awayadmin", "HR", "COMPANY_1",
                  with_employee=False)
    employee = attendance_service.get_own_employee(seeded, worker)
    record = Attendance(
        employee_id=employee.id,
        attendance_date=attendance_service.today(),
        attendance_status="ABSENT",
    )
    seeded.add(record)
    seeded.commit()

    updated = attendance_service.correct_record(
        seeded, admin, record.id,
        {"attendance_status": "ON_LEAVE", "remarks": "Approved leave."},
    )

    assert updated.attendance_status == "ON_LEAVE"
    assert updated.worked_minutes is None


def test_an_unknown_status_cannot_be_corrected_in(
    seeded: Session, make_user
) -> None:
    worker = staff(seeded, make_user, "badstatus", "EMPLOYEE", "DEPARTMENT_1")
    admin = staff(seeded, make_user, "badstatusadmin", "HR", "COMPANY_1",
                  with_employee=False)
    record = attendance_service.check_in(seeded, worker)

    with pytest.raises(AttendanceError):
        attendance_service.correct_record(
            seeded, admin, record.id, {"attendance_status": "SNOOZING"}
        )


# ===========================================================================
# Dashboard
# ===========================================================================


def test_dashboard_totals_agree_with_the_list(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "dashadmin", "SUPER_ADMIN", "HQ", with_employee=False)
    headers = login_headers("dashadmin")

    summary = client.get("/api/attendance/dashboard", headers=headers).json()
    listed = client.get(
        "/api/attendance", headers=headers, params={"page_size": 1}
    ).json()

    assert summary["total_records"] == listed["total"]
    assert summary["total_records"] >= seeded_attendance_under("HQ")
    # The statuses partition the whole, so nothing is double-counted or lost.
    assert sum(s["value"] for s in summary["by_status"]) == summary["total_records"]


def test_the_dashboard_respects_business_unit_scope(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "d_hq", "SUPER_ADMIN", "HQ", with_employee=False)
    staff(seeded, make_user, "d_br", "MANAGER", "BRANCH_1", with_employee=False)

    hq = client.get("/api/attendance/dashboard", headers=login_headers("d_hq")).json()
    br = client.get("/api/attendance/dashboard", headers=login_headers("d_br")).json()

    assert br["total_records"] < hq["total_records"]
    assert br["total_worked_hours"] < hq["total_worked_hours"]
    assert hq["total_records"] >= seeded_attendance_under("HQ")


def test_an_employees_dashboard_shows_only_their_own(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    user = staff(seeded, make_user, "solo", "EMPLOYEE", "DEPARTMENT_1")
    attendance_service.check_in(seeded, user)

    summary = client.get(
        "/api/attendance/dashboard", headers=login_headers("solo")
    ).json()

    assert summary["total_records"] == 1
    assert summary["incomplete_today"] == 1


def test_attendance_widgets_are_served_with_live_scoped_values(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    """The metadata chain end to end: shape stays configuration, numbers are live."""
    staff(seeded, make_user, "w_hq", "SUPER_ADMIN", "HQ", with_employee=False)
    staff(seeded, make_user, "w_br", "MANAGER", "BRANCH_1", with_employee=False)

    hq = client.get(
        "/api/access/dashboards/ATTENDANCE_OVERVIEW/data",
        headers=login_headers("w_hq"),
    )
    br = client.get(
        "/api/access/dashboards/ATTENDANCE_OVERVIEW/data",
        headers=login_headers("w_br"),
    )
    assert hq.status_code == 200, hq.text
    assert br.status_code == 200, br.text

    hq_data, br_data = hq.json(), br.json()
    assert hq_data["TOTAL_HOURS"]["value"] > br_data["TOTAL_HOURS"]["value"]
    assert set(hq_data["ATTENDANCE_TREND"]) == {"categories", "series"}
    assert set(hq_data["HOURS_BY_EMPLOYEE"]) == {"categories", "series"}
    assert "series" in hq_data["ATTENDANCE_BY_STATUS"]
    # Zero-count statuses are dropped so pie labels cannot collide.
    assert all(s["value"] > 0 for s in hq_data["ATTENDANCE_BY_STATUS"]["series"])


def test_an_employee_cannot_reach_the_attendance_dashboard_metadata(
    client: TestClient, seeded: Session, make_user, login_headers
) -> None:
    staff(seeded, make_user, "nodash", "EMPLOYEE", "DEPARTMENT_1")
    headers = login_headers("nodash")

    assert client.get(
        "/api/access/screens/ATTENDANCE_DASHBOARD/dashboards", headers=headers
    ).status_code == 404
    assert client.get(
        "/api/access/dashboards/ATTENDANCE_OVERVIEW/data", headers=headers
    ).status_code == 404


def test_the_seed_is_idempotent(seeded: Session) -> None:
    """Re-running it must change nothing, including the generated fixtures."""
    from app.metadata.seed import seed_all

    changed = seed_all(seeded)

    assert changed["attendance"] == 0
    assert changed["timesheets"] == 0
    assert changed["timesheet_history"] == 0
    assert changed["workflows"] == 0
    assert changed["workflow_states"] == 0
