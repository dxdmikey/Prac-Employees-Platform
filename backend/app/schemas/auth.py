"""
Pydantic schemas for authentication.

These describe what the API accepts and what it returns. They are separate
from the SQLAlchemy models on purpose: the User model has a password_hash
column, and none of the schemas below include it, so it cannot leak into a
response by accident.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.core.security import MAX_PASSWORD_BYTES


class LoginRequest(BaseModel):
    """Body of POST /api/auth/login."""

    username: str = Field(min_length=1, max_length=50)
    # The upper bound matches what bcrypt can hash, so an over-long password
    # is rejected with a readable 422 instead of failing deeper in the stack.
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_BYTES)


class UserResponse(BaseModel):
    """Public view of a user. Note there is no password_hash field."""

    # from_attributes lets FastAPI build this straight from a SQLAlchemy User.
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    first_name: str
    last_name: str
    is_active: bool


class LoginResponse(BaseModel):
    """Body returned by a successful POST /api/auth/login."""

    access_token: str
    # "bearer" tells the client how to send it back:
    #   Authorization: Bearer <access_token>
    token_type: str = "bearer"
    user: UserResponse


class MessageResponse(BaseModel):
    """Simple acknowledgement, used by logout."""

    message: str
