from __future__ import annotations

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from stockflow.db.models import Base


def get_database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg://stockflow:stockflow@db:5432/stockflow",
    )


engine: AsyncEngine = create_async_engine(
    get_database_url(),
    echo=False,
    future=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session