"""
Pydantic schemas for the health endpoints.

A Pydantic schema describes the shape of data crossing the API boundary, and is
the counterpart to a SQLAlchemy model, which describes the shape of data in the
database. Keeping them separate means the database can change without
automatically changing the public API - and it stops internal columns such as
password_hash from leaking into a response by accident.

Only these two schemas exist for now; request/response schemas for users,
roles and the rest arrive when their endpoints are built.
"""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response of GET /api/health."""

    status: str
    service: str


class DatabaseHealthResponse(BaseModel):
    """Response of GET /api/health/db."""

    status: str
    database: str
