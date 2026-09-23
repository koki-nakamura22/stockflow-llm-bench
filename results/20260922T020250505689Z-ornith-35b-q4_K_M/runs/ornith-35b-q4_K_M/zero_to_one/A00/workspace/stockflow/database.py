"""Database engine, session, and connection utilities."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://stockflow:stockflow@db:5432/stockflow",
)

_engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

_SessionLocal = sessionmaker(
    bind=_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a new DB session."""
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """Context manager for getting a DB session outside FastAPI."""
    session = _SessionLocal()
    try:
        yield session
    finally:
        session.close()


def check_db_connection() -> bool:
    """Check if the database is reachable."""
    try:
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
