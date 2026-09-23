"""Outbox worker for publishing events."""
import os
import uuid
from datetime import datetime
from typing import Any

import requests
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import JSONB

EVENT_PUBLISH_URL = os.environ.get("EVENT_PUBLISH_URL", "http://localhost:8080/events")
MAX_ATTEMPTS = 10


def publish_event(session: Session) -> int:
    """Publish one event from the outbox.

    Returns the number of events published.
    """
    published = 0

    # Get the last processed event_id and event_type to avoid duplicates
    last_event_id = session.scalar(select(Outbox.event_id).order_by(Outbox.event_id.desc()).limit(1))
    last_event_type = session.scalar(select(Outbox.event_type).order_by(Outbox.event_type.desc()).limit(1))

    # Find unprocessed events with unique event_id and event_type
    stmt = (
        select(Outbox)
        .where(
            Outbox.sent_at.is_(None),
            Outbox.processed_at.is_(None),
            Outbox.attempts < MAX_ATTEMPTS,
        )
        .where(
            Outbox.event_id != last_event_id,
            Outbox.event_type != last_event_type,
        )
        .order_by(Outbox.event_id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )

    outbox_entry = session.scalar(stmt)
    if not outbox_entry:
        return published

    payload = outbox_entry.payload
    headers = {"Idempotency-Key": str(outbox_entry.event_id)}

    try:
        response = requests.post(
            EVENT_PUBLISH_URL,
            json=payload,
            headers=headers,
            timeout=5,
        )

        if response.status_code < 200 or response.status_code >= 300:
            raise requests.HTTPError(f"HTTP {response.status_code}: {response.text}")

        outbox_entry.sent_at = datetime.utcnow()
        outbox_entry.processed_at = datetime.utcnow()
        session.commit()
        published += 1
    except requests.HTTPError as exc:
        outbox_entry.attempts += 1
        outbox_entry.last_error = str(exc)
        session.commit()
    except Exception as exc:  # noqa: BLE001
        outbox_entry.attempts += 1
        outbox_entry.last_error = str(exc)
        session.commit()

    return published


def run_once(session: Session) -> int:
    """Run the worker once."""
    return publish_event(session)


if __name__ == "__main__":
    from stockflow.models import Outbox
    from stockflow.db import SessionLocal

    with SessionLocal() as session:
        published = run_once(session)
        print(f"Published {published} event(s)")