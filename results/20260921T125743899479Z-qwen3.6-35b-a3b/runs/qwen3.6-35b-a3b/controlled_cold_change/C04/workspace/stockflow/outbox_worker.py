"""Outbox event publisher worker."""
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from stockflow.db import DATABASE_URL, engine
from stockflow.models import OutboxEvent

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

PUBLISH_URL = os.environ.get("EVENT_PUBLISH_URL", "")
BATCH_SIZE = int(os.environ.get("OUTBOX_BATCH_SIZE", "10"))


def claim_events(session: Session) -> list[OutboxEvent]:
    """Claim up to BATCH_SIZE unsent events using SKIP LOCKED."""
    stmt = (
        select(OutboxEvent)
        .where(
            OutboxEvent.sent_at.is_(None),
            OutboxEvent.attempts < 5,
        )
        .order_by(OutboxEvent.created_at)
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    events = session.scalars(stmt).all()
    return events


def publish_event(session: Session, event: OutboxEvent) -> None:
    """Publish a single outbox event to the external service."""
    payload = {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "aggregate_id": str(event.aggregate_id),
        "occurred_at": event.occurred_at.isoformat(),
        "payload": event.payload,
    }
    headers = {"Idempotency-Key": str(event.id), "Content-Type": "application/json"}
    try:
        resp = httpx.post(PUBLISH_URL, json=payload, headers=headers, timeout=10)
        if 200 <= resp.status_code < 300:
            event.sent_at = datetime.now(timezone.utc)
            session.commit()
        else:
            event.attempts += 1
            event.last_error = f"HTTP {resp.status_code}"
            session.commit()
    except Exception as exc:
        event.attempts += 1
        event.last_error = str(exc)
        session.commit()


def run_once() -> int:
    """Run one iteration of the outbox worker. Returns number of events processed."""
    with SessionLocal() as session:
        events = claim_events(session)
        count = 0
        for event in events:
            publish_event(session, event)
            count += 1
        return count


def main() -> None:
    """Entry point for the outbox worker."""
    if "--once" in sys.argv:
        count = run_once()
        print(f"Published {count} events")
        return

    print("Outbox worker running...")
    while True:
        count = run_once()
        if count == 0:
            import time
            time.sleep(2)


if __name__ == "__main__":
    main()
