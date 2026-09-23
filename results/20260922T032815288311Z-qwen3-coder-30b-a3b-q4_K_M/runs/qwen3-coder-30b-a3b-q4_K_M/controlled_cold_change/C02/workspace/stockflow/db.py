import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from stockflow.models import Base, IdempotencyKey

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://stockflow:stockflow@db:5432/stockflow"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base.metadata.create_all(bind=engine)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session

