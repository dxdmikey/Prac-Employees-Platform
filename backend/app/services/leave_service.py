"""
Leave Management business logic.

Everything here is assembled from existing platform pieces:

  * visibility  - business_unit_service (Stage 5) + one permission check
  * transitions - the generic workflow engine (Stage 7), never a direct write
                  to current_state_id
  * ownership   - the signed-in user's linked employee record (Stage 8)

There is no leave-specific authorisation table and no role name anywhere in
this module. Who may approve is the APPROVE permission plus the
LEAVE_APPROVAL workflow's transition roles - both metadata.

The visibility rule, which every read goes through:

    you can always see your own requests;
    you can see other people's only if you hold the APPROVE permission AND
    their employee sits inside your business-unit scope.

That second clause is what stops jane (Department 1) seeing her colleagues'
leave while still letting raj (Branch 1, APPROVE) see all of Branch 1.
"""

from datetime import date

from sqlalchemy import Select, false, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.employee import Employee
from app.models.leave_request import LeaveRequest
from app.models.leave_type import LeaveType
from app.models.user import User
from app.models.workflow_state import WorkflowState
from app.services import business_unit_service, rbac_service
from app.workflows import engine
from app.workflows.exceptions import TransitionNotAuthorized

LEAVE_WORKFLOW_CODE = "LEAVE_APPROVAL"
APPROVER_PERMISSION = "APPROVE"

# Two state codes, and the only two in this module.
#
# The workflow metadata marks a state initial or final, but it has no marker
# for "this final state means yes" versus "this one means no". The dashboard
# needs that distinction for its Approved and Rejected tiles, so the codes are
# named here and nowhere else. Every other rule below is derived from the
# metadata itself - see _is_owner_action.
APPROVED_STATE_CODE = "APPROVED"
REJECTED_STATE_CODE = "REJECTED"

MAX_PAGE_SIZE = 100


class LeaveError(Exception):
    """A request the leave rules refuse. The API turns it into a 400/403/404."""


class LeaveNotVisible(LeaveError):
    """The record exists but the caller may not see it."""


class LeaveNoEmployee(LeaveError):
    """The signed-in user has no employee record, so cannot own leave."""


# ---------------------------------------------------------------------------
# Who is asking
# ---------------------------------------------------------------------------


def get_own_employee(db: Session, user: User) -> Employee | None:
    """The employee record linked to this login, if there is one."""
    return db.scalar(select(Employee).where(Employee.user_id == user.id))


def require_own_employee(db: Session, user: User) -> Employee:
    employee = get_own_employee(db, user)
    if employee is None:
        raise LeaveNoEmployee(
            "Your account is not linked to an employee record, so you cannot "
            "raise leave requests. Ask an administrator to link it."
        )
    return employee


def _can_manage(db: Session, user: User) -> bool:
    return rbac_service.has_permission(db, user, APPROVER_PERMISSION)


# ---------------------------------------------------------------------------
# Visibility - the one query every read starts from
# ---------------------------------------------------------------------------


def _visible_query(db: Session, user: User) -> Select:
    own = get_own_employee(db, user)
    conditions = []
    if own is not None:
        conditions.append(LeaveRequest.employee_id == own.id)

    if _can_manage(db, user):
        visible_units = business_unit_service.get_user_visible_business_unit_ids(db, user)
        if visible_units:
            conditions.append(
                LeaveRequest.employee_id.in_(
                    select(Employee.id).where(Employee.business_unit_id.in_(visible_units))
                )
            )

    query = select(LeaveRequest).options(
        selectinload(LeaveRequest.employee).selectinload(Employee.business_unit),
        selectinload(LeaveRequest.leave_type),
        selectinload(LeaveRequest.current_state),
        selectinload(LeaveRequest.workflow),
    )
    # No own record and no scope means no requests - never all of them.
    # `false()` rather than a Python False: SQLAlchemy renders it as a real
    # SQL predicate, and the query returns nothing instead of everything.
    return query.where(or_(*conditions)) if conditions else query.where(false())


def get_visible_request(db: Session, user: User, request_id: int) -> LeaveRequest:
    request = db.scalar(_visible_query(db, user).where(LeaveRequest.id == request_id))
    if request is None:
        raise LeaveNotVisible("No leave request with that id is available to you.")
    return request


def list_requests(
    db: Session,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
    mine_only: bool = False,
    state_code: str | None = None,
    pending_only: bool = False,
) -> tuple[list[LeaveRequest], int]:
    """A page of visible requests, newest first."""
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)

    query = _visible_query(db, user)

    if mine_only:
        own = get_own_employee(db, user)
        query = query.where(LeaveRequest.employee_id == (own.id if own else -1))

    if state_code:
        query = query.where(
            LeaveRequest.current_state_id.in_(
                select(WorkflowState.id).where(WorkflowState.code == state_code)
            )
        )
    elif pending_only:
        # "Awaiting a decision", without naming a state: past the start, not
        # yet at an end. Every middle state of the workflow qualifies, so the
        # approval queue keeps working unchanged if a second approval step is
        # inserted into the metadata later.
        query = query.where(
            LeaveRequest.current_state_id.in_(
                select(WorkflowState.id).where(
                    WorkflowState.is_initial.is_(False),
                    WorkflowState.is_final.is_(False),
                )
            )
        )

    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = list(
        db.scalars(
            query.order_by(LeaveRequest.created_at.desc(), LeaveRequest.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return rows, int(total or 0)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def calculate_total_days(start: date, end: date) -> int:
    """
    Calendar days, both ends inclusive: 14th to 16th is 3 days.

    Deliberately simple - no weekends or public holidays yet. That is a later
    stage, and it will change this one function only.
    """
    if end < start:
        raise LeaveError("The end date cannot be before the start date.")
    days = (end - start).days + 1
    if days <= 0:
        raise LeaveError("A leave request must cover at least one day.")
    return days


def _active_leave_type(db: Session, leave_type_id: int) -> LeaveType:
    leave_type = db.get(LeaveType, leave_type_id)
    if leave_type is None or not leave_type.is_active:
        raise LeaveError("That leave type does not exist or is not active.")
    return leave_type


def _require_editable(request: LeaveRequest) -> None:
    """
    A request may be edited only while it sits in its workflow's *initial*
    state - which for LEAVE_APPROVAL is Draft.

    Asking `is_initial` rather than comparing against the string "DRAFT" is
    what keeps this metadata-driven: renaming the state, or reusing this
    service for a workflow whose first state is called something else, needs
    no change here. Once a request has moved on, editing it would change what
    an approver already saw.
    """
    if not request.current_state.is_initial:
        raise LeaveError(
            f"This request is {request.current_state.name} and can no longer be edited."
        )


def _require_owner(request: LeaveRequest, employee: Employee | None) -> None:
    if employee is None or request.employee_id != employee.id:
        raise LeaveNotVisible("Only the employee who raised this request may do that.")


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def create_request(db: Session, user: User, data: dict) -> LeaveRequest:
    """
    Raise a request for the signed-in user's own employee record.

    The owner is never taken from the request body, and the state is whatever
    the LEAVE_APPROVAL workflow marks as initial.
    """
    employee = require_own_employee(db, user)
    _active_leave_type(db, data["leave_type_id"])
    total_days = calculate_total_days(data["start_date"], data["end_date"])

    workflow = engine.get_workflow(db, LEAVE_WORKFLOW_CODE)
    initial_state = engine.get_initial_state(db, workflow)

    request = LeaveRequest(
        employee_id=employee.id,
        leave_type_id=data["leave_type_id"],
        start_date=data["start_date"],
        end_date=data["end_date"],
        total_days=total_days,
        reason=data.get("reason"),
        workflow_id=workflow.id,
        current_state_id=initial_state.id,
    )
    db.add(request)
    db.flush()
    # The opening history line joins this same commit.
    engine.record_initial_state(db, request, user, comments="Created")
    db.commit()
    return get_visible_request(db, user, request.id)


def update_request(db: Session, user: User, request_id: int, changes: dict) -> LeaveRequest:
    """
    Edit a draft you own. Dates re-run the duration calculation.

    Takes an id, not a record. The service resolves it through the visibility
    query itself, so the scope rule cannot be skipped by a caller that already
    has a LeaveRequest object in its hand.
    """
    request = get_visible_request(db, user, request_id)
    _require_owner(request, get_own_employee(db, user))
    _require_editable(request)

    if "leave_type_id" in changes and changes["leave_type_id"] is not None:
        _active_leave_type(db, changes["leave_type_id"])
        request.leave_type_id = changes["leave_type_id"]

    start = changes.get("start_date") or request.start_date
    end = changes.get("end_date") or request.end_date
    request.total_days = calculate_total_days(start, end)
    request.start_date, request.end_date = start, end

    if "reason" in changes:
        request.reason = changes["reason"]

    db.commit()
    db.refresh(request)
    return request


# ---------------------------------------------------------------------------
# Workflow - delegated to the engine
# ---------------------------------------------------------------------------


def _is_owner_action(transition) -> bool:
    """
    Is this an action for the person who raised the request, or for someone
    else deciding on it?

    The rule is read off the metadata rather than written down as a list of
    transition codes: **a transition that leaves the workflow's initial state
    belongs to the owner; any later transition belongs to someone else.**

    For LEAVE_APPROVAL that resolves exactly as intended - Submit and Cancel
    both leave Draft, so they are the employee's; Approve and Reject leave
    Pending Approval, so they are the approver's. Add a transition to the
    metadata tomorrow and it is classified without touching this file.

    It is also what prevents self-approval: an owner is never offered an
    action that starts after the initial state, even if their role would
    otherwise allow it. A manager cannot approve their own leave.
    """
    return transition.from_state.is_initial


def available_transitions(db: Session, user: User, request_id: int):
    """
    The engine's answer, narrowed by ownership.

    The engine knows which *roles* may perform a transition. It deliberately
    does not know the caller's relationship to the record - that is
    application knowledge, and this is the application. So the metadata answer
    comes first, and ownership filters it.

    Resolving the record here rather than accepting one means a caller can
    never be offered actions on a request outside their business-unit scope.
    """
    request = get_visible_request(db, user, request_id)
    own = get_own_employee(db, user)
    is_owner = own is not None and own.id == request.employee_id

    return [
        transition
        for transition in engine.get_available_transitions(db, request, user)
        if _is_owner_action(transition) == is_owner
    ]


def execute_transition(
    db: Session, user: User, request_id: int, transition_code: str, comments: str | None
) -> LeaveRequest:
    """
    Perform a transition through the engine - the only way a state changes.

    Three separate questions are asked, and all three are asked *here* rather
    than in the route, because a rule written in an endpoint protects only
    that endpoint:

      1. may this caller see this request at all?   business-unit scope
      2. does the metadata allow this transition?   the engine
      3. is this caller the right person for it?    ownership

    Taking an id rather than a record is what makes (1) unskippable. An
    earlier version accepted a LeaveRequest and trusted it, which left the
    scope check sitting in the API route - so the service was safe only as
    long as every future caller remembered to fetch the record the careful
    way. It no longer depends on anyone remembering.

    Note what this function never does: assign to `request.current_state_id`.
    The engine makes that write together with the history row, in one
    transaction, so a state change without an audit entry cannot happen.
    """
    request = get_visible_request(db, user, request_id)

    allowed = {t.code for t in available_transitions(db, user, request_id)}
    if transition_code not in allowed:
        # Distinguish "the metadata forbids this" from "the metadata allows it
        # but you are the wrong person". The engine explains the first kind in
        # its own words - unknown code, wrong state, missing role - so only the
        # ownership failure is worded here.
        engine_allowed = {
            t.code for t in engine.get_available_transitions(db, request, user)
        }
        if transition_code in engine_allowed:
            raise TransitionNotAuthorized(
                "That action is not available to you on this request - "
                "requests are submitted and cancelled by the employee who "
                "raised them, and approved or rejected by someone else."
            )

    engine.execute_transition(db, request, transition_code, user, comments)
    return get_visible_request(db, user, request_id)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def get_dashboard_summary(db: Session, user: User) -> dict:
    """
    Aggregates over exactly the requests the caller may see.

    The visible query is reused as a subquery, so the dashboard can never
    count a request the caller could not open. That is the whole point: an
    employee's totals are their own leave, a manager's are their branch, and
    neither is a different code path - it is the same WHERE clause.

    State names come from the workflow metadata, so renaming a state in the
    database renames it on the chart with no change here.
    """
    visible = _visible_query(db, user).order_by(None).subquery()

    # code -> how many visible requests sit in that state right now.
    counts = {
        code: count
        for code, count in db.execute(
            select(WorkflowState.code, func.count(visible.c.id))
            .join(visible, visible.c.current_state_id == WorkflowState.id)
            .group_by(WorkflowState.code)
        )
    }

    by_type = [
        {"name": name, "value": count}
        for name, count in db.execute(
            select(LeaveType.name, func.count(visible.c.id))
            .join(visible, visible.c.leave_type_id == LeaveType.id)
            .group_by(LeaveType.name)
            .order_by(func.count(visible.c.id).desc(), LeaveType.name)
        )
    ]

    # Every state of the leave workflow, in its configured order, so the chart
    # keeps a stable shape even before a state has been reached for the first
    # time. Zero-count states are dropped from the slice list by the widget
    # resolver, not here - the raw numbers stay honest.
    workflow = engine.get_workflow(db, LEAVE_WORKFLOW_CODE, require_active=False)
    by_status = [
        {"name": state.name, "value": counts.get(state.code, 0)}
        for state in engine.get_states(db, workflow)
    ]

    # to_char gives "2026-09"; ordering the string orders the months, because
    # a zero-padded year-month sorts the same way lexically and chronologically.
    by_month = [
        {"name": month, "value": count}
        for month, count in db.execute(
            select(
                func.to_char(visible.c.start_date, "YYYY-MM").label("month"),
                func.count(visible.c.id),
            )
            .group_by("month")
            .order_by("month")
        )
    ]

    total_days = db.scalar(
        select(func.coalesce(func.sum(visible.c.total_days), 0)).select_from(visible)
    )

    # Pending is derived, not named: anything that has left the initial state
    # without reaching a final one is waiting on somebody.
    pending = sum(
        counts.get(state.code, 0)
        for state in engine.get_states(db, workflow)
        if not state.is_initial and not state.is_final
    )

    return {
        "total_requests": sum(counts.values()),
        "pending": pending,
        "approved": counts.get(APPROVED_STATE_CODE, 0),
        "rejected": counts.get(REJECTED_STATE_CODE, 0),
        "total_days_requested": int(total_days or 0),
        "by_type": by_type,
        "by_status": by_status,
        "by_month": by_month,
    }
