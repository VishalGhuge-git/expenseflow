"""SQLAlchemy engine, session factory, and FastAPI DB dependency for ExpenseFlow."""

import os
from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///expenseflow.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for a single request, closing it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables registered on Base.metadata if they don't already exist.

    Imports app.models here (not at module level) so every model class is
    registered on Base.metadata before create_all runs, without creating a
    circular import with models.py (which imports Base from this module).
    """
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
