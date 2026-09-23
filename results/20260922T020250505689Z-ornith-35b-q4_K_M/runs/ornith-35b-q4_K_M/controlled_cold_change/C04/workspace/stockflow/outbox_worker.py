"""Outbox event publisher worker.

Usage:
    python -m stockflow.outbox_worker --once
    python -m stockflow.outbox_worker          # loop until interrupted
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from stockflow.db import engine
from stockflow.models import OutboxEvent

logger = logging.getLogger(__name__)

EVENT_PUBLISH_URL = os.environ.get("EVENT_PUBLISH_URL", "")
PUBLISH_TIMEOUT = float(os.environ.get("PUBLISH_TIMEOUT", "10"))
POLL_INTERVAL = float(os.environ.get("OUTBOX_POLL_INTERVAL", "2"))


def publish_event(session: Session, event: OutboxEvent) -> None:
    """Publish a single outbox event to EVENT_PUBLISH_URL.

    On success (2xx), set ``sent_at``. On failure, increment ``attempts``
    and record ``last_error`` so the event remains unsent.
    """
    headers = {"Idempotency-Key": str(event.id), "Content-Type": "application/json"}
    payload = {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "aggregate_id": str(event.aggregate_id),
        "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
        "payload": event.payload,
    }
    try:
        resp = httpx.post(
            EVENT_PUBLISH_URL,
            json=payload,
            headers=headers,
            timeout=PUBLISH_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        event.attempts += 1
        event.last_error = f"{type(exc).__name__}: {exc}"
        session.add(event)
        session.commit()
        logger.warning("publish failed (attempt %d): %s", event.attempts, exc)
        return

    if 200 <= resp.status_code < 300:
        event.sent_at = datetime.now(timezone.utc)
        session.add(event)
        session.commit()
        logger.info("published event %s (%s)", event.id, event.event_type)
    else:
        event.attempts += 1
        event.last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        session.add(event)
        session.commit()
        logger.warning(
            "publish returned %s (attempt %d): %s",
            resp.status_code,
            event.attempts,
            event.last_error,
        )


def claim_next(session: Session) -> OutboxEvent | None:
    """Select one unsent outbox event row, locked for this worker.

    Uses ``FOR UPDATE SKIP LOCKED`` so multiple workers never collide on
    the same row. Returns ``None`` when no events are available.
    """
    stmt = (
        select(OutboxEvent)
        .where(
            or_(
                OutboxEvent.sent_at.is_(None),
                OutboxEvent.sent_at < datetime.now(timezone.utc) - timedelta(seconds=300),
            ),
            OutboxEvent.attempts < 20,
        )
        .order_by(OutboxEvent.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    event = session.scalar(stmt)
    return event  # type: ignore[return-value]


def run_once(session: Session) -> int:
    """Publish as many events as available in one pass. Returns count published."""
    published = 0
    while True:
        event = claim_next(session)
        if event is None:
            break
        publish_event(session, event)
        published += 1
    return published


def main() -> None:
    parser = argparse.ArgumentParser(description="StockFlow outbox worker")
    parser.add_argument("--once", action="store_true", help="Publish pending events once and exit")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not EVENT_PUBLISH_URL:
        logger.error("EVENT_PUBLISH_URL is not set; exiting.")
        raise SystemExit(1)

    with Session(engine) as session:
        if args.once:
            count = run_once(session)
            logger.info("outbox --once: published %d event(s)", count)
            return

    # Loop mode: run forever until interrupted.
    while True:
        try:
            with Session(engine) as session:
                count = run_once(session)
                if count == 0:
                    time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            logger.info("outbox worker stopped")
            break
        except Exception:  # pragma: no cover - defensive
            logger.exception("outbox loop error")
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":  # pragma: no cover
    main()
