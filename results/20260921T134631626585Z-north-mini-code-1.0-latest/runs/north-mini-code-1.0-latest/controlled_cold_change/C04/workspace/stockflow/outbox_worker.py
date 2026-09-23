#!/usr/bin/env python3
"""
Transactional outbox worker.
Processes unsent outbox events and publishes them via HTTP.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from stockflow.db import SessionLocal
from stockflow.models import Outbox

EVENT_PUBLISH_URL = os.environ.get("EVENT_PUBLISH_URL")


def publish_event(event: Outbox) -> bool:
    """Publish a single outbox event. Return True on success."""
    if not EVENT_PUBLISH_URL:
        raise RuntimeError("EVENT_PUBLISH_URL environment variable not set")
    headers = {"Idempotency-Key": str(event.event_id)}
    # event.payload is a dict (JSONB). Ensure it's JSON serializable.
    try:
        with httpx.Client() as client:
            resp = client.post(
                EVENT_PUBLISH_URL,
                json=event.payload,
                headers=headers,
                timeout=10.0,
            )
    except Exception as e:
        event.attempts += 1
        event.last_error = str(e)[:500]
        return False

    if 200 <= resp.status_code < 300:
        return True
    else:
        event.attempts += 1
        event.last_error = f"HTTP {resp.status_code}: {resp.text[:500]}"
        return False


def process_outbox(session: Session, batch_size: int = 10):
    """Process unsent outbox events.
    Locks rows for update to prevent concurrent processing.
    """
    # Select unsent events with a FOR UPDATE SKIP LOCKED to avoid race conditions
    stmt = (
        select(Outbox)
        .where(Outbox.sent_at.is_(None))
        .order_by(Outbox.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    events = session.execute(stmt).scalars().all()
    if not events:
        print("No unsent outbox events.")
        return

    for event in events:
        success = publish_event(event)
        if success:
            event.sent_at = datetime.now(timezone.utc)
            event.last_error = None
            session.add(event)
            print(f"Published event {event.event_id} ({event.event_type})")
        else:
            # attempt already incremented in publish_event
            session.add(event)
            print(f"Failed to publish event {event.event_id} (attempt {event.attempts}): {event.last_error}")

    session.commit()


def main():
    parser = argparse.ArgumentParser(description="Process outbox events.")
    parser.add_argument("--once", action="store_true", help="Process a single batch and exit")
    parser.add_argument("--batch-size", type=int, default=10, help="Number of events to process in one batch")
    args = parser.parse_args()

    if not EVENT_PUBLISH_URL:
        print("ERROR: EVENT_PUBLISH_URL environment variable is not set", file=sys.stderr)
        sys.exit(1)

    while True:
        with SessionLocal() as session:
            process_outbox(session, batch_size=args.batch_size)
        if args.once:
            break
        # Sleep before next iteration (e.g., 5 seconds)
        import time
        time.sleep(5)


if __name__ == "__main__":
    main()