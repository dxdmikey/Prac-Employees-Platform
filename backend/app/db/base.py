"""
The declarative Base class that every SQLAlchemy model inherits from.

Base carries the "metadata" object - SQLAlchemy's in-memory catalogue of every
table it knows about. Alembic reads Base.metadata to work out what the database
*should* look like, then compares it against what the database *does* look like.

Kept in its own small module so models can import Base without importing the
engine, which avoids circular imports.
"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Parent class for all ORM models."""


class TimestampMixin:
    """
    Adds created_at / updated_at to a model.

    server_default=func.now() means PostgreSQL fills the value in, so rows get
    correct timestamps even when they are inserted outside the application.
    onupdate=func.now() makes SQLAlchemy refresh updated_at on every UPDATE.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
