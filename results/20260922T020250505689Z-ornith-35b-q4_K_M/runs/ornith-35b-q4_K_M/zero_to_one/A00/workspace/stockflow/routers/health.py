"""Health check router."""

from __future__ import annotations

from fastapi import APIRouter

from stockflow.database import check_db_connection

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Health check endpoint. Returns 200 only if DB connection is successful."""
    if check_db_connection():
        return {"status": "ok"}
    else:
        raise Exception("Database connection failed")
