"""Pydantic schemas for the business unit hierarchy."""

from pydantic import BaseModel, ConfigDict, Field


class BusinessUnitTypeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None = None
    display_order: int
    is_active: bool


class BusinessUnitResponse(BaseModel):
    """One unit, flat. parent_id is None for a root."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None = None
    parent_id: int | None = None
    business_unit_type_id: int
    is_active: bool


class BusinessUnitNode(BaseModel):
    """
    One unit with its children nested inside it.

    The self-reference in the annotation is what makes this a tree of any
    depth - a node contains nodes.
    """

    id: int
    code: str
    name: str
    parent_id: int | None = None
    business_unit_type_id: int
    business_unit_type_code: str
    business_unit_type_name: str
    is_active: bool
    children: list["BusinessUnitNode"] = []


class BusinessUnitCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=150)
    business_unit_type_id: int = Field(gt=0)
    parent_id: int | None = None
    description: str | None = None


class BusinessUnitUpdateRequest(BaseModel):
    """
    Every field is optional - send only what changes.

    `parent_id` is special: a request that simply omits it must not move the
    unit to the top of the tree, so the endpoint checks whether the field was
    supplied at all before touching it.
    """

    name: str | None = Field(default=None, min_length=1, max_length=150)
    business_unit_type_id: int | None = Field(default=None, gt=0)
    parent_id: int | None = None
    description: str | None = None
    is_active: bool | None = None


class AssignBusinessUnitRequest(BaseModel):
    """Body of POST /api/users/{user_id}/business-units."""

    business_unit_id: int = Field(gt=0)


class BusinessUnitAccessResponse(BaseModel):
    """
    The answer from the combined RBAC + scope check.

    Returned only on success; a failure is an HTTP error, not a `false` here,
    so a caller cannot mistake a denial for a granted request.
    """

    business_unit_id: int
    business_unit_code: str
    business_unit_name: str
    access: bool
    reason: str


class MyBusinessUnitsResponse(BaseModel):
    """What the signed-in user can see of the organisation."""

    assigned: list[BusinessUnitResponse]
    visible: list[BusinessUnitResponse]
