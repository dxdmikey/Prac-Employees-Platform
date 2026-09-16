"""LeaveType model - the kinds of leave an organisation offers."""

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class LeaveType(Base, TimestampMixin):
    """
    Annual, Sick, Casual, Unpaid... as rows, not a Python enum.

    A new kind of leave is an INSERT. `max_days` is informational for now -
    a balance engine that enforces it is a later stage.
    """

    __tablename__ = "leave_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    max_days: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                            default=True, server_default="true")

    def __repr__(self) -> str:
        return f"<LeaveType id={self.id} code={self.code!r}>"
