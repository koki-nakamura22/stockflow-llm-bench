"""Outbox event worker – publishes pending events to EVENT_PUBLISH_URL."""

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Iterator

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from stockflow.db import SessionLocal, engine
from stockflow.models import OutboxEvent

logger = logging.getLogger(__name__)

PUBLISH_URL = os.environ.get("EVENT_PUBLISH_URL", "")
BATCH_SIZE = 10
CLAIM_TIMEOUT = 5  # seconds for row-level lock


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def claim_pending(session: Session, limit: int = BATCH_SIZE) -> list[OutboxEvent]:
    """Claim up to `limit` pending events with a row-level lock so multiple
    workers do not claim the same event concurrently."""
    stmt = (
        select(OutboxEvent)
        .where(OutboxEvent.sent_at.is_(None))
        .order_by(OutboxEvent.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    events = session.scalars(stmt).all()
    return events


def publish_event(event: OutboxEvent) -> None:
    """POST the event JSON to EVENT_PUBLISH_URL with Idempotency-Key header.
    On 2xx set sent_at. On failure increment attempts / last_error."""
    payload = json.dumps({
        "event_id": str(event.event_id),
        "event_type": event.event_type,
        "aggregate_id": str(event.aggregate_id),
        "occurred_at": event.occurred_at.isoformat(),
        "payload": json.loads(event.payload),
    })
    headers = {"Idempotency-Key": str(event.event_id), "Content-Type": "application/json"}

    try:
        with httpx.Client() as client:
            resp = client.post(PUBLISH_URL, content=payload, headers=headers, timeout=10)
            if 200 <= resp.status_code < 300:
                event.sent_at = datetime.now(timezone.utc)
            else:
                raise httpx.HTTPStatusError(
                    f"Unexpected status {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
    except Exception as exc:
        event.attempts += 1
        event.last_error = str(exc)
        raise


def run_once() -> int:
    """Claim and publish pending events. Returns number of events processed."""
    processed = 0
    with get_session() as session:
        events = claim_pending(session, limit=BATCH_SIZE)
        for event in events:
            try:
                publish_event(event)
                processed += 1
            except Exception:
                logger.exception("Failed to publish event %s", event.event_id)
        session.commit()
    return processed


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")
    if not PUBLISH_URL:
        logger.warning("EVENT_PUBLISH_URL not set – nothing to do")
        return
    while True:
        count = run_once()
        logger.info("Published %d events", count)
        if count == 0:
            break
        time.sleep(1)


if __name__ == "__main__":
    main()
