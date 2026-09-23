import os
from collections.abc import Iterator
from uuid import UUID

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from stockflow.models import Outbox

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://stockflow:stockflow@db:5432/stockflow"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def claim_outbox_events(session: Session, batch_size: int = 10) -> list:
    """Lock-unlock pattern for at-least-once delivery"""
    stmt = (
        select(Outbox)
        .where(Outbox.lock_version == 0, Outbox.sent_at == Outbox.lock_version)
        .with_for_update(skip_locked=True)
        .order_by(Outbox.id)
        .limit(batch_size)
    )
    return list(session.scalars(stmt))


def mark_outbox_sent(session: Session, event_ids: list[UUID]) -> None:
    stmt = text(
        """
        UPDATE outbox
        SET sent_at = now(),
            lock_version = lock_version + 1
        WHERE id = ANY(:event_ids)
        """
    )
    session.execute(stmt, {"event_ids": event_ids})


def mark_outbox_failed(
    session: Session, event_ids: list[UUID], last_error: str
) -> None:
    stmt = text(
        """
        UPDATE outbox
        SET attempts = attempts + 1,
            last_error = :last_error,
            lock_version = lock_version + 1
        WHERE id = ANY(:event_ids)
        """
    )
    session.execute(stmt, {"event_ids": event_ids, "last_error": last_error})

