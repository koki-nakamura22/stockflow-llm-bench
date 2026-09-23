"""Transactional outbox worker – publishes pending events via HTTP POST."""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from stockflow.db import SessionLocal, engine
from stockflow.models import OutboxEvent

logger = logging.getLogger(__name__)


PUBLISH_URL = os.environ.get("EVENT_PUBLISH_URL", "http://localhost:9999/events")


def claim_one(session: Session) -> OutboxEvent | None:
    """Atomically claim the oldest unsent event (SKIP LOCKED for concurrency safety)."""
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.sent_at.is_(None))
        .order_by(OutboxEvent.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    event = session.scalar(stmt)
    return event


def publish(event: OutboxEvent) -> bool:
    """POST the event payload to EVENT_PUBLISH_URL. Returns True on 2xx."""
    headers = {"Idempotency-Key": str(event.event_id), "Content-Type": "application/json"}
    payload = {
        "event_id": str(event.event_id),
        "event_type": event.event_type,
        "aggregate_id": str(event.aggregate_id),
        "occurred_at": event.occurred_at.isoformat(),
        "payload": event.payload,
    }
    try:
        resp = httpx.post(PUBLISH_URL, json=payload, headers=headers, timeout=10)
        return resp.status_code >= 200 and resp.status_code < 300
    except httpx.HTTPError as exc:
        logger.error("publish failed: %s", exc)
        return False


def run_once() -> int:
    """Claim and publish one event. Returns 1 if published, 0 if no events."""
    session = SessionLocal()
    try:
        event = claim_one(session)
        if event is None:
            return 0
        success = publish(event)
        if success:
            event.sent_at = datetime.now(timezone.utc)
            session.commit()
            logger.info("published event %s", event.event_id)
            return 1
        else:
            event.attempts += 1
            event.last_error = "HTTP request failed"
            session.commit()
            logger.warning("failed to publish event %s (attempts=%d)", event.event_id, event.attempts)
            return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Outbox event publisher")
    parser.add_argument("--once", action="store_true", help="Publish one event and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.once:
        count = run_once()
        sys.exit(0 if count else 1)
    else:
        logger.info("no --once flag; nothing to do")
        sys.exit(0)


if __name__ == "__main__":
    main()
