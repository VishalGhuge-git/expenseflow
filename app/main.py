"""FastAPI application entrypoint for ExpenseFlow."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import init_db
from app.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Create database tables on startup if they don't already exist."""
    init_db()
    yield


app = FastAPI(title="ExpenseFlow", lifespan=lifespan)
app.include_router(router)
