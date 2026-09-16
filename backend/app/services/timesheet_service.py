"""
Timesheet business logic.

The third application built on the same four pieces, and the second driven by
the generic workflow engine:

  * visibility  - employee_scope, shared with Leave and Attendance
  * transitions - the Stage 7 engine, never a direct write to current_state_id
  * ownership   - the signed-in user's linked employee record
  * who may act - the TIMESHEET_APPROVAL workflow's transition roles

No role name appears in this module, and no state name is used to make a
decision. Both come from metadata:

    is_initial              may this still be edited?
    is_owner_held           is this record on its author's desk or an
                            approver's? - which is what the pending queue asks
    transition.actor        is this action the author's, or an approver's?

The last one is why REJECTED -> DRAFT works. Revise is marked OWNER, so it is
offered to the author and not to the manager who rejected it - without this
module knowing that any of those states exist.
"""

from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.models.employee import Employee
from app.models.timesheet import Timesheet
from app.models.user import User
from app.models.workflow_state import WorkflowState
from app.services import employee_scope
from app.workflows import engine, ownership
from app.workflows.exceptions import TransitionNotAuthorized

TIMESHEET_WORKFLOW_CODE = "TIMESHEET_APPROVAL"

# The two state codes named in this module, and the only two.
#
# The metadata marks a state initial, final or owner-held, but has no marker
# for "this outcome means yes" as opposed to "no". The dashboard needs that
# distinction for its Approved and Rejected tiles, so the codes are named
# here. Every other rule below is derived.
APPROVED_STATE_CODE = "APPROVED"
REJECTED_STATE_CODE = "REJECTED"

MAX_PAGE_SIZE = 100
MINUTES_PER_HOUR = 60


class TimesheetError(Exception):
    """A request the timesheet rules refuse. The API turns it into 400/403/409."""


class TimesheetNotVisible(TimesheetError):
    """The record exists but the caller may not see it."""


class TimesheetNoEmployee(TimesheetError):
    """The signed-in user has no employee record, so cannot record work."""


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------


def hours_to_minutes(hours: float) -> int:
    """
    Convert what a person types into what the column stores.

    Rounded to the nearest minute, then checked: a positive number of hours
    that rounds to zero minutes is a mistake worth reporting rather than a
    zero-length entry worth saving.
    """
    minutes = int(round(hours * MINUTES_PER_HOUR))
    if minutes <= 0:
        raise TimesheetError("A timesheet entry must be at least one minute long.")
    if minutes > 24 * MINUTES_PER_HOUR:
        raise TimesheetError("A timesheet entry cannot be longer than 24 hours.")
    return minutes


def minutes_to_hours(minutes: int) -> float:
    """One definition of how a duration is presented, used by every response."""
    return round(minutes / MINUTES_PER_HOUR, 2)


# ---------------------------------------------------------------------------
# Who is asking
# ---------------------------------------------------------------------------


def get_own_employee(db: Session, user: User) -> Employee | None:
    return employee_scope.get_own_employee(db, user)


def require_own_employee(db: Session, user: User) -> Employee:
    employee = employee_scope.get_own_employee(db, user)
    if employee is None:
        raise TimesheetNoEmployee(
            "Your account is not linked to an employee record, so you cannot "
            "record work. Ask an administrator to link it."
        )
    return employee


# ---------------------------------------------------------------------------
# Visibility
# ---------------------------------------------------------------------------


def _visible_query(db: Session, user: User) -> Select:
    """The base query for every timesheet read. Nothing bypasses it."""
    return (
        select(Timesheet)
        .options(
            selectinload(Timesheet.employee).selectinload(Employee.business_unit),
            selectinload(Timesheet.current_state),
            selectinload(Timesheet.workflow),
        )
        .where(employee_scope.visible_employee_filter(db, user, Timesheet.employee_id))
    )


def get_visible_timesheet(db: Session, user: User, timesheet_id: int) -> Timesheet:
    entry = db.scalar(_visible_query(db, user).where(Timesheet.id == timesheet_id))
    if entry is None:
        raise TimesheetNotVisible("No timesheet with that id is available to you.")
    return entry


def list_timesheets(
    db: Session,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
    mine_only: bool = False,
    employee_id: int | None = None,
    state_code: str | None = None,
    pending_only: bool = False,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[Timesheet], int]:
    """A page of visible timesheets, most recent work date first."""
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)

    query = _visible_query(db, user)

    if mine_only:
        own = get_own_employee(db, user)
        query = query.where(Timesheet.employee_id == (own.id if own else -1))

    if employee_id is not None:
        query = query.where(Timesheet.employee_id == employee_id)

    if state_code:
        query = query.where(
            Timesheet.current_state_id.in_(
                select(WorkflowState.id).where(WorkflowState.code == state_code)
            )
        )
    elif pending_only:
        # "Waiting on an approver", without naming a state: it has left the
        # author's hands and has not finished. Derived from the two metadata
        # flags, so inserting a second approval step would not break this.
        query = query.where(
            Timesheet.current_state_id.in_(
                select(WorkflowState.id).where(
                    WorkflowState.is_owner_held.is_(False),
                    WorkflowState.is_final.is_(False),
                )
            )
        )

    if date_from is not None:
        query = query.where(Timesheet.work_date >= date_from)
    if date_to is not None:
        query = query.where(Timesheet.work_date <= date_to)

    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = list(
        db.scalars(
            query.order_by(Timesheet.work_date.desc(), Timesheet.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return rows, int(total or 0)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _require_editable(entry: Timesheet) -> None:
    """
    An entry may be edited only while it sits in its workflow's initial state.

    Asking `is_initial` rather than comparing against "DRAFT" is what keeps
    this metadata-driven. It is also why a *rejected* entry is not editable
    until its author revises it back into draft: rejected is on their desk,
    but the workflow has not reopened it for changes yet.
    """
    if not entry.current_state.is_initial:
        raise TimesheetError(
            f"This timesheet is {entry.current_state.name} and can no longer "
            "be edited."
        )


def _require_owner(entry: Timesheet, employee: Employee | None) -> None:
    if employee is None or entry.employee_id != employee.id:
        raise TimesheetNotVisible(
            "Only the employee who recorded this work may do that."
        )


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def create_timesheet(db: Session, user: User, data: dict) -> Timesheet:
    """
    Record work against the signed-in user's own employee record.

    The owner is never taken from the request body, and the state is whatever
    the workflow marks as initial.
    """
    employee = require_own_employee(db, user)
    minutes = hours_to_minutes(data["hours"])

    workflow = engine.get_workflow(db, TIMESHEET_WORKFLOW_CODE)
    initial_state = engine.get_initial_state(db, workflow)

    entry = Timesheet(
        employee_id=employee.id,
        work_date=data["work_date"],
        minutes=minutes,
        work_description=data["work_description"].strip(),
        reference=(data.get("reference") or None),
        workflow_id=workflow.id,
        current_state_id=initial_state.id,
    )
    db.add(entry)
    db.flush()
    # The opening history line joins this same commit, so an entry and its
    # first history row appear together or not at all.
    engine.record_initial_state(db, entry, user, comments="Created")
    db.commit()
    return get_visible_timesheet(db, user, entry.id)


def update_timesheet(
    db: Session, user: User, timesheet_id: int, changes: dict
) -> Timesheet:
    """
    Edit a draft you own.

    Takes an id, not a record, so the visibility rule is resolved here and
    cannot be skipped by a caller holding a Timesheet object.
    """
    entry = get_visible_timesheet(db, user, timesheet_id)
    _require_owner(entry, get_own_employee(db, user))
    _require_editable(entry)

    if changes.get("work_date") is not None:
        entry.work_date = changes["work_date"]
    if changes.get("hours") is not None:
        entry.minutes = hours_to_minutes(changes["hours"])
    if changes.get("work_description") is not None:
        entry.work_description = changes["work_description"].strip()
    if "reference" in changes:
        entry.reference = changes["reference"] or None

    db.commit()
    db.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# Workflow - delegated to the engine
# ---------------------------------------------------------------------------


def available_transitions(db: Session, user: User, timesheet_id: int):
    """
    The engine's answer, narrowed by ownership.

    The engine knows which *roles* may perform a transition; it deliberately
    does not know the caller's relationship to the record. That is application
    knowledge, and this is the application.
    """
    entry = get_visible_timesheet(db, user, timesheet_id)
    own = get_own_employee(db, user)
    is_owner = own is not None and own.id == entry.employee_id

    # Submit and Revise are marked OWNER on the TIMESHEET_APPROVAL
    # transitions, Approve and Reject OTHER. Revise is the interesting one:
    # it leaves REJECTED, which is not the workflow's first state, and it is
    # still the author's action - which is why the marking lives on the
    # transition rather than being inferred from where it starts.
    return ownership.filter_for_caller(
        engine.get_available_transitions(db, entry, user), is_owner=is_owner
    )


def execute_transition(
    db: Session,
    user: User,
    timesheet_id: int,
    transition_code: str,
    comments: str | None,
) -> Timesheet:
    """
    Perform a transition through the engine - the only way a state changes.

    Three questions, all asked here rather than in the route, because a rule
    written in an endpoint protects only that endpoint:

      1. may this caller see this timesheet?      business-unit scope
      2. does the metadata allow this transition? the engine
      3. is this caller the right person for it?  ownership

    Note what this never does: assign to `entry.current_state_id`. The engine
    makes that write together with the history row, in one transaction, so a
    state change without an audit entry cannot happen.
    """
    entry = get_visible_timesheet(db, user, timesheet_id)

    allowed = {t.code for t in available_transitions(db, user, timesheet_id)}
    if transition_code not in allowed:
        # Tell the two failures apart. The engine explains a metadata refusal
        # in its own words - unknown code, wrong state, missing role - so only
        # the ownership refusal is worded here.
        engine_allowed = {
            t.code for t in engine.get_available_transitions(db, entry, user)
        }
        if transition_code in engine_allowed:
            raise TransitionNotAuthorized(
                "That action is not available to you on this timesheet - work "
                "is submitted and revised by the employee who recorded it, and "
                "approved or rejected by someone else."
            )

    engine.execute_transition(db, entry, transition_code, user, comments)
    return get_visible_timesheet(db, user, timesheet_id)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def get_dashboard_summary(db: Session, user: User) -> dict:
    """Aggregates over exactly the timesheets the caller may see."""
    visible = _visible_query(db, user).order_by(None).subquery()

    counts = {
        code: count
        for code, count in db.execute(
            select(WorkflowState.code, func.count(visible.c.id))
            .join(visible, visible.c.current_state_id == WorkflowState.id)
            .group_by(WorkflowState.code)
        )
    }
    minutes_by_state = {
        code: minutes or 0
        for code, minutes in db.execute(
            select(WorkflowState.code, func.sum(visible.c.minutes))
            .join(visible, visible.c.current_state_id == WorkflowState.id)
            .group_by(WorkflowState.code)
        )
    }

    workflow = engine.get_workflow(db, TIMESHEET_WORKFLOW_CODE, require_active=False)
    states = engine.get_states(db, workflow)

    total_minutes = int(
        db.scalar(
            select(func.coalesce(func.sum(visible.c.minutes), 0)).select_from(visible)
        )
        or 0
    )

    hours_by_employee = [
        {"name": name, "value": int(round((minutes or 0) / MINUTES_PER_HOUR))}
        for name, minutes in db.execute(
            select(
                (Employee.first_name + " " + Employee.last_name).label("full_name"),
                func.sum(visible.c.minutes),
            )
            .join(visible, visible.c.employee_id == Employee.id)
            .group_by("full_name")
            .order_by(func.sum(visible.c.minutes).desc().nulls_last())
            .limit(10)
        )
    ]

    # Grouped by ISO week, so a month of entries becomes four or five points
    # rather than thirty. to_char gives "2026-W38", which sorts correctly as
    # text because the week number is zero-padded.
    hours_by_week = [
        {"name": week, "value": int(round((minutes or 0) / MINUTES_PER_HOUR))}
        for week, minutes in db.execute(
            select(
                func.to_char(visible.c.work_date, 'IYYY-"W"IW').label("week"),
                func.sum(visible.c.minutes),
            )
            .group_by("week")
            .order_by("week")
        )
    ]

    # "Submitted" is derived, not named: it has left the author and has not
    # finished, so it is waiting on somebody.
    submitted = sum(
        counts.get(state.code, 0)
        for state in states
        if not state.is_owner_held and not state.is_final
    )
    # "Draft" is the initial state, not simply "owner-held and unfinished" -
    # a rejected entry is also back with its author, and counting it as a
    # draft would hide the rejection behind a reassuring number.
    draft = sum(counts.get(state.code, 0) for state in states if state.is_initial)

    return {
        "total_entries": sum(counts.values()),
        "draft": draft,
        "submitted": submitted,
        "approved": counts.get(APPROVED_STATE_CODE, 0),
        "rejected": counts.get(REJECTED_STATE_CODE, 0),
        "total_hours": minutes_to_hours(total_minutes),
        "approved_hours": minutes_to_hours(
            int(minutes_by_state.get(APPROVED_STATE_CODE, 0))
        ),
        "by_status": [
            {"name": state.name, "value": counts.get(state.code, 0)}
            for state in states
        ],
        "hours_by_employee": hours_by_employee,
        "hours_by_week": hours_by_week,
    }
