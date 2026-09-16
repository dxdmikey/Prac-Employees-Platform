"""
Whether a transition belongs to a record's owner, or to somebody else.

The engine answers one question: *which roles may perform this transition?*
Every business application so far has needed a second one - *and is this
caller the right person?* - because a manager may approve timesheets without
being allowed to approve their own. That second question is not the engine's
to answer, because the engine has no idea what "owner" means for an arbitrary
entity. So it lives here, in one place, read from metadata.

Three applications ask it now: Leave, Timesheets and Expenses. Before this
module they each had their own `_is_owner_action`, which is three chances for
the same rule to drift.

**How the rule got here.** It has been wrong twice, and both corrections are
worth keeping in view:

  Stage 9   inferred it from `from_state.is_initial` - "an owner acts first".
            True of leave, and of nothing else.
  Stage 10  moved it to `from_state.is_owner_held` - "whose desk is it on?".
            That fixed a rejected timesheet returning to its author to revise,
            an owner action out of a state that is not the first one.
  Stage 11  moved it onto the transition itself, because the two can
            genuinely disagree. An expense in SUBMITTED is on the approver's
            desk - the pending queue is right to say so - and yet Cancel, the
            claimant withdrawing their own claim, leaves that same state and
            belongs to the owner.

The state flag survives, because "whose desk is this on?" is a real and
separate question that the pending queues ask. What moved is only "who
performs this action?", which was always a property of the action.
"""

from app.models.workflow_transition import WorkflowTransition


def is_owner_action(transition: WorkflowTransition) -> bool | None:
    """
    True if only the owner may perform it, False if only somebody else may,
    and None if the metadata does not care.

    None is not "nobody" - it is "no relationship is required", which is how
    the Stage 7 demo workflow behaves and why nothing about it changed.
    """
    if transition.actor == "OWNER":
        return True
    if transition.actor == "OTHER":
        return False
    return None


def filter_for_caller(
    transitions: list[WorkflowTransition], *, is_owner: bool
) -> list[WorkflowTransition]:
    """
    Narrow the engine's answer to the transitions this particular caller may
    perform, given whether they own the record.

    Used by every workflow-driven application, so the four cases are decided
    once:

        actor=OWNER, caller owns it        -> offered
        actor=OWNER, caller does not       -> withheld
        actor=OTHER, caller owns it        -> withheld  (no self-approval)
        actor=OTHER, caller does not       -> offered
        actor=ANY                          -> offered either way
    """
    return [
        transition
        for transition in transitions
        if is_owner_action(transition) in (None, is_owner)
    ]
