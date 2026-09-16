"""
The generic workflow engine.

There is exactly one of these. It knows nothing about expenses, leave or
payroll - it reads workflow metadata and applies it. Every future application
that needs an approval process uses this module unchanged; what differs
between them is rows in the database, not code here.

The contract an entity must satisfy is small. It needs:

    id                 its primary key
    __tablename__      used as the history entity_type
    workflow_id        which process governs it
    current_state_id   where it is now

`WorkflowDemoRequest` is the first such entity. An `Expense` model in a later
stage will carry the same four things and work here with no changes.

Authorization reuses the existing RBAC roles through `rbac_service`. The engine
never mentions a role name; it asks which roles the user holds and compares
that against the roles the metadata attached to the transition.
"""

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.models.user import User
from app.models.workflow import Workflow
from app.models.workflow_history import WorkflowHistory
from app.models.workflow_state import WorkflowState
from app.models.workflow_transition import WorkflowTransition
from app.services import rbac_service
from app.workflows.exceptions import (
    StateNotFound,
    TransitionNotAuthorized,
    TransitionNotAvailable,
    TransitionNotFound,
    WorkflowError,
    WorkflowInactive,
    WorkflowNotFound,
)


# ---------------------------------------------------------------------------
# Reading the definition
# ---------------------------------------------------------------------------


def get_workflow(db: Session, workflow_code: str, *, require_active: bool = True) -> Workflow:
    """Load a workflow by code, or raise."""
    workflow = db.scalar(select(Workflow).where(Workflow.code == workflow_code))
    if workflow is None:
        raise WorkflowNotFound(f"No workflow with code {workflow_code}.")
    if require_active and not workflow.is_active:
        raise WorkflowInactive(f"The workflow {workflow.name} is not active.")
    return workflow


def list_workflows(db: Session) -> list[Workflow]:
    return list(db.scalars(select(Workflow).order_by(Workflow.code)))


def get_states(db: Session, workflow: Workflow) -> list[WorkflowState]:
    return list(
        db.scalars(
            select(WorkflowState)
            .where(WorkflowState.workflow_id == workflow.id)
            .order_by(WorkflowState.display_order, WorkflowState.code)
        )
    )


def get_transitions(db: Session, workflow: Workflow) -> list[WorkflowTransition]:
    return list(
        db.scalars(
            select(WorkflowTransition)
            .options(
                selectinload(WorkflowTransition.from_state),
                selectinload(WorkflowTransition.to_state),
                selectinload(WorkflowTransition.allowed_roles),
            )
            .where(WorkflowTransition.workflow_id == workflow.id)
            .order_by(WorkflowTransition.code)
        )
    )


def get_initial_state(db: Session, workflow: Workflow) -> WorkflowState:
    """
    Where a brand-new record starts.

    A workflow with no initial state is misconfigured, and saying so plainly
    here is far kinder than letting a record be created with no state at all.
    """
    state = db.scalar(
        select(WorkflowState).where(
            WorkflowState.workflow_id == workflow.id,
            WorkflowState.is_initial.is_(True),
            WorkflowState.is_active.is_(True),
        )
    )
    if state is None:
        raise StateNotFound(
            f"The workflow {workflow.name} has no initial state configured."
        )
    return state


def get_current_state(db: Session, entity) -> WorkflowState:
    """The state a record is in now, checked against its own workflow."""
    state = db.get(WorkflowState, entity.current_state_id)
    if state is None or state.workflow_id != entity.workflow_id:
        raise StateNotFound("The current state of this record is not valid.")
    return state


# ---------------------------------------------------------------------------
# Authorization - delegated to the existing RBAC layer
# ---------------------------------------------------------------------------


def can_execute_transition(
    db: Session,
    transition: WorkflowTransition,
    user: User,
    user_role_ids: set[int] | None = None,
) -> bool:
    """
    May this user perform this transition?

    The engine holds no role names. It asks RBAC which roles the user has and
    checks whether any of them appears in the transition's allowed_roles - a
    metadata list. Changing who may approve is an INSERT or a DELETE.

    A transition with no roles attached is performable by nobody. Failing
    closed is the safe default: unfinished configuration must not become an
    open door.
    """
    allowed_role_ids = {role.id for role in transition.allowed_roles}
    if not allowed_role_ids:
        return False

    # A caller checking several transitions passes the roles in once, so the
    # RBAC lookup is not repeated for every arrow.
    if user_role_ids is None:
        user_role_ids = {role.id for role in rbac_service.get_user_roles(db, user)}
    return bool(allowed_role_ids & user_role_ids)


def get_available_transitions(
    db: Session, entity, user: User
) -> list[WorkflowTransition]:
    """
    What this user can do to this record, right now.

    Two filters, and both matter:

      1. the transition must start from the record's current state,
      2. the user must be authorized for it.

    This is what the UI renders its buttons from, which is why no React
    component ever decides which actions a role sees.
    """
    current_state = get_current_state(db, entity)
    user_role_ids = {role.id for role in rbac_service.get_user_roles(db, user)}

    return [
        transition
        for transition in get_transitions(db, entity.workflow)
        if transition.is_active
        and transition.from_state_id == current_state.id
        and can_execute_transition(db, transition, user, user_role_ids)
    ]


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def execute_transition(
    db: Session,
    entity,
    transition_code: str,
    user: User,
    comments: str | None = None,
) -> WorkflowHistory:
    """
    Move a record to its next state, and record that it happened.

    Everything is checked before anything is changed:

      1. the workflow exists and is active,
      2. the record's current state is valid and belongs to that workflow,
      3. the transition exists within that workflow,
      4. it starts from the current state,
      5. the user is authorized for it,
      6. the target state is valid and belongs to the same workflow.

    Only then are the two writes made - the new state on the record, and the
    history row - and they are committed together.

    **Why one transaction matters.** These two writes are one fact. If the
    state moved to APPROVED but the history insert failed, the record would
    claim to be approved with nothing saying who approved it or when: an audit
    trail with a hole in it, and no way to tell afterwards. Committing both or
    neither means the history can always be trusted to explain the state.
    """
    workflow = entity.workflow
    if workflow is None:
        raise WorkflowNotFound("This record is not attached to a workflow.")
    if not workflow.is_active:
        raise WorkflowInactive(f"The workflow {workflow.name} is not active.")

    current_state = get_current_state(db, entity)

    # Looked up *within this workflow*, so a transition code from another
    # process can never be smuggled in.
    transition = db.scalar(
        select(WorkflowTransition)
        .options(selectinload(WorkflowTransition.allowed_roles))
        .where(
            WorkflowTransition.workflow_id == workflow.id,
            WorkflowTransition.code == transition_code,
        )
    )
    if transition is None:
        raise TransitionNotFound(
            f"No transition {transition_code} in workflow {workflow.name}."
        )
    if not transition.is_active:
        raise TransitionNotAvailable(f"The {transition.name} action is not active.")

    if transition.from_state_id != current_state.id:
        raise TransitionNotAvailable(
            f"{transition.name} cannot be performed while this record is "
            f"{current_state.name}."
        )

    if not can_execute_transition(db, transition, user):
        raise TransitionNotAuthorized(
            f"Your roles do not allow you to perform {transition.name}."
        )

    target_state = db.get(WorkflowState, transition.to_state_id)
    if target_state is None or target_state.workflow_id != workflow.id:
        raise StateNotFound("The target state of this transition is not valid.")

    # --- the two writes, one transaction -----------------------------------
    history = WorkflowHistory(
        workflow_id=workflow.id,
        # Generic: the table name identifies the kind of record, so the engine
        # needs no knowledge of the entity itself.
        entity_type=entity.__tablename__,
        entity_id=entity.id,
        from_state_id=current_state.id,
        to_state_id=target_state.id,
        transition_id=transition.id,
        performed_by_user_id=user.id,
        comments=comments,
    )
    entity.current_state_id = target_state.id
    db.add(history)

    try:
        db.commit()
    except SQLAlchemyError as exc:
        # Undo both writes together, so the record never keeps a new state
        # that no history row explains.
        db.rollback()
        raise WorkflowError("The transition could not be saved.") from exc

    # Refresh the record too, not just the history row.
    #
    # The application session is created with expire_on_commit=False, so a
    # commit does NOT expire loaded attributes. Without this refresh the
    # entity keeps the current_state relationship it loaded before the
    # transition, and the caller reads back the *previous* state - the new
    # state is in the database, but not in this object.
    db.refresh(entity)
    db.refresh(history)
    return history


def record_initial_state(
    db: Session, entity, user: User, comments: str | None = None
) -> WorkflowHistory:
    """
    Write the opening history entry for a newly created record.

    from_state_id and transition_id are NULL here: the record did not move into
    its initial state, it began there. Recording it anyway means the history is
    a complete story rather than one that starts mid-way.

    The caller commits, so this joins the same transaction that creates the
    record - the entity and its first history row appear together or not at all.
    """
    history = WorkflowHistory(
        workflow_id=entity.workflow_id,
        entity_type=entity.__tablename__,
        entity_id=entity.id,
        from_state_id=None,
        to_state_id=entity.current_state_id,
        transition_id=None,
        performed_by_user_id=user.id,
        comments=comments,
    )
    db.add(history)
    return history


def get_history(db: Session, entity) -> list[WorkflowHistory]:
    """The full trail for one record, oldest first."""
    return list(
        db.scalars(
            select(WorkflowHistory)
            .options(
                selectinload(WorkflowHistory.from_state),
                selectinload(WorkflowHistory.to_state),
                selectinload(WorkflowHistory.transition),
                selectinload(WorkflowHistory.performed_by),
            )
            .where(
                WorkflowHistory.entity_type == entity.__tablename__,
                WorkflowHistory.entity_id == entity.id,
            )
            .order_by(WorkflowHistory.created_at, WorkflowHistory.id)
        )
    )
