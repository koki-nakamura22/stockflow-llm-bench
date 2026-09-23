"""Transactional outbox worker.

Run with: python -m stockflow.outbox_worker --once
"""
import argparse
import os
import sys

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from stockflow.db import SessionLocal
from stockflow.models import OutboxEvent


BATCH_SIZE = 10
PUBLISH_URL = os.environ.get("EVENT_PUBLISH_URL", "")
TIMEOUT = 10


def claim_events(session: Session) -> list[OutboxEvent]:
    """Claim up to BATCH_SIZE unclaimed events using SELECT FOR UPDATE SKIP LOCKED."""
    stmt = (
        select(OutboxEvent)
        .where(
            OutboxEvent.sent_at.is_(None),
            (OutboxEvent.attempts == 0) | (OutboxEvent.last_error.isnot(None)),
        )
        .order_by(OutboxEvent.created_at)
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    events = session.scalars(stmt).all()
    return events


def publish_event(session: Session, event: OutboxEvent) -> bool:
    """Publish a single outbox event. Returns True on success."""
    payload = {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "aggregate_id": str(event.aggregate_id),
        "occurred_at": event.created_at.isoformat(),
        "payload": event.payload,
    }
    try:
        resp = httpx.post(
            PUBLISH_URL,
            json=payload,
            headers={"Idempotency-Key": str(event.id)},
            timeout=TIMEOUT,
        )
        if 200 <= resp.status_code < 300:
            event.sent_at = event.created_at
            session.commit()
            return True
        else:
            raise httpx.HTTPStatusError(
                f"Unexpected status {resp.status_code}",
                request=resp.request,
                response=resp,
            )
    except Exception as exc:
        event.attempts += 1
        event.last_error = str(exc)
        session.commit()
        return False


def run_once() -> None:
    """Process one batch of outbox events."""
    if not PUBLISH_URL:
        print("EVENT_PUBLISH_URL not set, skipping", file=sys.stderr)
        return

    session = SessionLocal()
    try:
        events = claim_events(session)
        if not events:
            return

        for event in events:
            success = publish_event(session, event)
            status = "sent" if success else "failed"
            print(f"{event.id} {event.event_type} -> {status}")
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Outbox worker")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    args = parser.parse_args()

    if args.once:
        run_once()
    else:
        print("Usage: python -m stockflow.outbox_worker --once", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
