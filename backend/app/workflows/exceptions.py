"""
Errors the workflow engine raises.

Each one is a *business* failure, not a bug: the caller asked for something the
metadata does not allow. The API layer maps them to HTTP status codes, so the
engine itself stays free of FastAPI imports and can be used from a script or a
test just as easily as from a request.

Every message is safe to show a user - none of them exposes internals.
"""


class WorkflowError(Exception):
    """Base class, so a caller can catch every workflow failure at once."""


class WorkflowNotFound(WorkflowError):
    """No workflow with that code."""


class WorkflowInactive(WorkflowError):
    """The workflow exists but has been switched off."""


class StateNotFound(WorkflowError):
    """A state is missing, or does not belong to this workflow."""


class TransitionNotFound(WorkflowError):
    """No transition with that code in this workflow."""


class TransitionNotAvailable(WorkflowError):
    """
    The transition exists, but not from where the record is now.

    This is the rule that makes the engine trustworthy: DRAFT -> APPROVED is
    refused when only DRAFT -> PENDING_MANAGER_APPROVAL is configured.
    """


class TransitionNotAuthorized(WorkflowError):
    """The user's roles do not include any role allowed to perform this."""
