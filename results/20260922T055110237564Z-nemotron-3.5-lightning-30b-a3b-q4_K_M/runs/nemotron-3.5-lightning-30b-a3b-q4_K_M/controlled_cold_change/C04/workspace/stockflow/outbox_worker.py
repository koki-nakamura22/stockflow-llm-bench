"""Transactional outbox worker.

Sends pending outbox events to the EVENT_PUBLISH_URL via JSON POST with
Idempotency-Key header set to the event_id.

- Uses SELECT FOR UPDATE with a SKIP LOCKED clause to ensure multiple workers
  do not claim the same event.
- Updates sent_at on 2xx response; on failure records attempts/last_error and
  leaves sent_at NULL so it can be retried.
- at-least-once delivery guarantee.
"""
import os
import sys
import json
import time
from typing import Optional

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stockflow.db import get_session
from stockflow.models import Outbox


def _pick_url() -> str:
    url = os.getenv("EVENT_PUBLISH_URL")
    if not url:
        print("WARN: EVENT_PUBLISH_URL not set, worker exiting", file=sys.stderr)
        sys.exit(1)
    return url


def _publish(url: str, event: Outbox) -> bool:
    """Publish a single outbox event. Returns True on 2xx, False otherwise."""
    headers = {
        "Idempotency-Key": str(event.event_id),
        "Content-Type": "application/json",
    }
    body = {
        "event_id": str(event.event_id),
        "event_type": event.event_type,
        "aggregate_id": str(event.aggregate_id),
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "payload": json.loads(event.payload) if event.payload else {},
    }
    try:
        with httpx.Client(timeout=10) as client:
            r = client.post(url, headers=headers, json=body)
        if 200 <= r.status_code < 300:
            return True
        return False
    except Exception as exc:  # network error, timeout, etc.
        # Update error info and leave sent_at NULL for retry
        event.attempts += 1
        event.last_error = str(exc)
        return False


def worker_once(skip: int = 1) -> None:
    """Process one batch of pending outbox events.

    - Claims up to ``skip`` rows using ``FOR UPDATE`` with ``SKIP LOCKED`` so
      multiple workers do not pick the same row.
    - Attempts to publish each event.
    - On success: sets ``sent_at = now()`` and clears ``attempts`` / ``last_error``.
    - On failure: increments ``attempts`` and stores ``last_error``; ``sent_at``
      stays NULL so the row can be retried.
    """
    url = _pick_url()
    with get_session() as session:
        # Select pending events, locked with SKIP LOCKED for safe multi-worker claim
        stmt = (
            select(Outbox)
            .where(Outbox.sent_at.is_(None))
            .order_by(Outbox.occurred_at)
            .limit(skip)
            .with_for_update(skip_locked=True)
        )
        events = session.scalars(stmt).all()

        if not events:
            print("No pending outbox events")
            return

        now = text("now()")
        for event in events:
            published = _publish(url, event)
            if published:
                event.sent_at = func.now()
                event.attempts = 0
                event.last_error = None
                print(f"Sent outbox event {event.event_id} ({event.event_type})")
            else:
                event.attempts += 1
                # last_error already set in _publish if it was an HTTP error
                print(
                    f"Failed outbox event {event.event_id} ({event.event_type}), "
                    f"attempt {event.attempts}",
                    file=sys.stderr,
                )
        session.commit()


def main() -> None:
    """Entry point for ``python -m stockflow.outbox_worker --once``."""
    import argparse

    parser = argparse.ArgumentParser(description="Transactional outbox worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one batch of pending events and exit",
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=1,
        help="Number of events to claim in one batch (default: 1)",
    )
    args = parser.parse_args()

    if args.once:
        worker_once(skip=args.skip)
    else:
        # Simple loop forever, polling every 5 seconds
        print("Starting outbox worker loop (Ctrl-C to stop)", file=sys.stderr)
        try:
            while True:
                worker_once(skip=args.skip)
                time.sleep(5)
        except KeyboardInterrupt:
            print("\nWorker stopped", file=sys.stderr)


if __name__ == "__main__":
    main()