"""ExpenseCategory model - the kinds of expense an organisation reimburses."""

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ExpenseCategory(Base, TimestampMixin):
    """
    Travel, Meals, Hotel... as rows, not a Python enum and not a list in React.

    The same reasoning as `leave_types`: this is business configuration that
    genuinely varies between organisations, so adding "Client Entertainment"
    is an INSERT rather than a code change and a deploy.

    Contrast with `ATTENDANCE_STATUSES`, which *is* a Python tuple. The
    difference is whether code has to branch on the value. Nothing branches on
    a category - it is carried, grouped and displayed - so it belongs in a
    table. Attendance statuses are computed from timestamps by code that must
    know them all, so a table would add a join and buy nothing.
    """

    __tablename__ = "expense_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Retiring a category must not rewrite history: existing expenses keep
    # pointing at it, and it simply stops being offered on the form.
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    def __repr__(self) -> str:
        return f"<ExpenseCategory id={self.id} code={self.code!r}>"
