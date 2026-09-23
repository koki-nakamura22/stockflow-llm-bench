"""Outbox worker: publishes pending outbox events to EVENT_PUBLISH_URL."""

import json
import os
import sys
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from stockflow.db import SessionLocal
from stockflow.models import OutboxEvent


PUBLISH_URL = os.environ.get("EVENT_PUBLISH_URL", "")
BATCH_SIZE = 100


def claim_pending(session: Session) -> list[OutboxEvent]:
    """Claim up to BATCH_SIZE pending events for a single worker."""
    stmt = (
        select(OutboxEvent)
        .where(
            OutboxEvent.sent_at.is_(None),
            (OutboxEvent.attempts == 0)
            | (OutboxEvent.last_error.isnot(None)),
        )
        .order_by(OutboxEvent.id)
        .limit(BATCH_SIZE)
    )
    events = session.scalars(stmt).all()
    # Mark as claimed by incrementing attempts (optimistic claim)
    for ev in events:
        ev.attempts += 1
    session.commit()
    return events


def publish_event(event: OutboxEvent) -> bool:
    """Publish a single event to EVENT_PUBLISH_URL. Returns True on success."""
    if not PUBLISH_URL:
        return True  # No URL configured, skip

    payload = json.loads(event.payload)
    headers = {"Idempotency-Key": str(event.event_id), "Content-Type": "application/json"}

    try:
        with httpx.Client() as client:
            resp = client.post(PUBLISH_URL, json=payload, headers=headers, timeout=10)
            if 200 <= resp.status_code < 300:
                return True
            return False
    except Exception:
        return False


def run_once() -> int:
    """Run one pass of the outbox worker. Returns number of events published."""
    published = 0
    with SessionLocal() as session:
        events = claim_pending(session)
        for event in events:
            success = publish_event(event)
            if success:
                event.sent_at = datetime.now(timezone.utc)
                event.last_error = None
                published += 1
            else:
                event.last_error = "publish_failed"
        session.commit()
    return published


def main() -> None:
    """Entry point for --once mode."""
    count = run_once()
    print(f"Published {count} events", file=sys.stderr)


if __name__ == "__main__":
    main()
