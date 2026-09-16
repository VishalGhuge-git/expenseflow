"""Pydantic v2 request/response models for ExpenseFlow."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED


class ExpenseCreate(BaseModel):
    """Request body for submitting a new expense."""

    description: str = Field(min_length=1)
    amount_minor: int = Field(gt=0, description="Amount in integer minor units (e.g. cents), must be positive.")
    currency: str = Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        description="ISO 4217 3-letter currency code, e.g. 'USD'.",
    )
    category: str = Field(min_length=1)
    submitted_by: str = Field(min_length=1)


class ExpenseOut(BaseModel):
    """Full expense record returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    submitted_by: str
    description: str
    category: str
    amount_minor: int
    currency: str = Field(validation_alias="original_currency")
    fx_rate_micros: int
    amount_base_minor: int
    status: Literal[STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED]
    rejection_reason: str | None
    decided_by: str | None
    created_at: datetime
    decided_at: datetime | None


class ApproveRequest(BaseModel):
    """Request body for approving a pending expense."""

    decided_by: str = Field(min_length=1)


class RejectRequest(BaseModel):
    """Request body for rejecting a pending expense."""

    decided_by: str = Field(min_length=1)
    reason: str | None = None
