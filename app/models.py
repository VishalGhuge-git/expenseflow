"""SQLAlchemy ORM models for ExpenseFlow."""

from datetime import datetime, timezone

from sqlalchemy import CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
VALID_STATUSES = (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED)


def _utcnow() -> datetime:
    """Return the current UTC time, used as the default for created_at."""
    return datetime.now(timezone.utc)


class Expense(Base):
    """An expense submission, its INR conversion, and its approval decision.

    `status` is constrained to VALID_STATUSES by a DB-level CHECK constraint,
    which is the source of truth; the pydantic schemas layer should mirror the
    same enum so invalid values are rejected before they ever reach the DB.
    """

    __tablename__ = "expenses"
    __table_args__ = (
        CheckConstraint(
            f"status IN {VALID_STATUSES!r}",
            name="ck_expenses_status_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    submitted_by: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(nullable=False)
    category: Mapped[str] = mapped_column(nullable=False)

    amount_minor: Mapped[int] = mapped_column(nullable=False)
    original_currency: Mapped[str] = mapped_column(nullable=False)
    fx_rate_micros: Mapped[int] = mapped_column(nullable=False)
    amount_base_minor: Mapped[int] = mapped_column(nullable=False)

    status: Mapped[str] = mapped_column(nullable=False, default=STATUS_PENDING)
    rejection_reason: Mapped[str | None] = mapped_column(default=None)
    decided_by: Mapped[str | None] = mapped_column(default=None)

    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(default=None)
