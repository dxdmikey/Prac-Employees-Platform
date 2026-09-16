"""Pydantic schemas for the workflow engine."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WorkflowStateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None = None
    is_initial: bool
    is_final: bool
    display_order: int
    is_active: bool


class WorkflowTransitionResponse(BaseModel):
    """
    One arrow, flattened for the UI.

    State codes are included alongside the ids so the frontend can draw the
    diagram without a second lookup, and `allowed_role_codes` makes the
    authorisation rule visible on the admin screen.
    """

    id: int
    code: str
    name: str
    description: str | None = None
    from_state_id: int
    from_state_code: str
    from_state_name: str
    to_state_id: int
    to_state_code: str
    to_state_name: str
    allowed_role_codes: list[str] = []
    is_active: bool


class WorkflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None = None
    application_id: int | None = None
    is_active: bool


class WorkflowDetailResponse(WorkflowResponse):
    """A workflow with its full definition, for the admin screen."""

    states: list[WorkflowStateResponse] = []
    transitions: list[WorkflowTransitionResponse] = []


# --- the demonstration entity ------------------------------------------------


class DemoRequestCreate(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    description: str | None = None


class DemoRequestResponse(BaseModel):
    """A demo record and where it currently sits."""

    id: int
    title: str
    description: str | None = None
    workflow_id: int
    workflow_code: str
    current_state_id: int
    current_state_code: str
    current_state_name: str
    is_final: bool
    created_by_user_id: int
    created_by_username: str
    created_at: datetime


class TransitionRequest(BaseModel):
    """
    Body of POST /api/workflow-demo/{id}/transition.

    The action is named by code rather than by target state: the metadata
    decides where SUBMIT leads, so a caller cannot choose its own destination.
    """

    transition_code: str = Field(min_length=1, max_length=50)
    comments: str | None = None


class WorkflowHistoryResponse(BaseModel):
    """One line of the audit trail."""

    id: int
    entity_type: str
    entity_id: int
    from_state_code: str | None = None
    from_state_name: str | None = None
    to_state_code: str
    to_state_name: str
    transition_code: str | None = None
    transition_name: str | None = None
    performed_by_user_id: int
    performed_by_username: str
    comments: str | None = None
    created_at: datetime
