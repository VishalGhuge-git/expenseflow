"""API routes for the ExpenseFlow submit -> convert -> approve/reject journey."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.db import get_db
from app.insights import generate_insight
from app.models import STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED, Expense
from app.schemas import ApproveRequest, ExpenseCreate, ExpenseOut, RejectRequest

router = APIRouter()


def _apply_decision(db: Session, expense_id: int, values: dict) -> Expense:
    """Atomically transition a pending expense, raising 404/409 if it can't be decided.

    The update only applies WHERE status = 'pending' so a concurrent second
    decision (or an approve after a reject) can't silently overwrite this one.
    """
    result = db.execute(
        update(Expense).where(Expense.id == expense_id, Expense.status == STATUS_PENDING).values(**values)
    )
    db.commit()
    expense = db.get(Expense, expense_id)
    if result.rowcount == 0:
        if expense is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Expense not found")
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=f"Expense is not pending (current status: {expense.status})",
        )
    return expense


@router.post("/expenses", response_model=ExpenseOut, status_code=http_status.HTTP_201_CREATED)
def create_expense(payload: ExpenseCreate, db: Session = Depends(get_db)) -> Expense:
    """Submit a new expense. Converted to base currency (INR) and set to pending."""
    # TODO: replace with a real FX lookup (httpx call to the rate provider) and
    # compute amount_base_minor = round(amount_minor * rate). Currently a 1:1 passthrough.
    expense = Expense(
        submitted_by=payload.submitted_by,
        description=payload.description,
        category=payload.category,
        amount_minor=payload.amount_minor,
        original_currency=payload.currency,
        fx_rate_micros=1_000_000,
        amount_base_minor=payload.amount_minor,
        status=STATUS_PENDING,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.get("/expenses", response_model=list[ExpenseOut])
def list_expenses(
    status: str | None = Query(default=None, description="Filter by status: pending, approved, or rejected."),
    category: str | None = Query(default=None, description="Filter by category."),
    db: Session = Depends(get_db),
) -> list[Expense]:
    """List expenses, optionally filtered by status and/or category."""
    query = db.query(Expense)
    if status is not None:
        query = query.filter(Expense.status == status)
    if category is not None:
        query = query.filter(Expense.category == category)
    return query.order_by(Expense.id).all()


@router.get("/expenses/{expense_id}", response_model=ExpenseOut)
def get_expense(expense_id: int, db: Session = Depends(get_db)) -> Expense:
    """Fetch one expense by id."""
    expense = db.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Expense not found")
    return expense


@router.post("/expenses/{expense_id}/approve", response_model=ExpenseOut)
def approve_expense(expense_id: int, payload: ApproveRequest, db: Session = Depends(get_db)) -> Expense:
    """Approve a pending expense."""
    return _apply_decision(
        db,
        expense_id,
        {
            "status": STATUS_APPROVED,
            "decided_by": payload.decided_by,
            "decided_at": datetime.now(timezone.utc),
        },
    )


@router.post("/expenses/{expense_id}/reject", response_model=ExpenseOut)
def reject_expense(expense_id: int, payload: RejectRequest, db: Session = Depends(get_db)) -> Expense:
    """Reject a pending expense, optionally recording a reason."""
    return _apply_decision(
        db,
        expense_id,
        {
            "status": STATUS_REJECTED,
            "decided_by": payload.decided_by,
            "decided_at": datetime.now(timezone.utc),
            "rejection_reason": payload.reason,
        },
    )


@router.get("/reports/insights")
def get_insights(db: Session = Depends(get_db)) -> dict:
    """Return a short natural-language summary of spending insights across all expenses."""
    expenses = db.query(Expense).order_by(Expense.id).all()
    expense_dicts = [
        {
            "amount_base_minor": expense.amount_base_minor,
            "category": expense.category,
            "status": expense.status,
        }
        for expense in expenses
    ]
    return {"insight": generate_insight(expense_dicts)}
