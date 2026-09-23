import os
import sys
import time
from datetime import datetime
from typing import List

import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from stockflow.db import get_session
from stockflow.models import Outbox

EVENT_PUBLISH_URL = os.getenv("EVENT_PUBLISH_URL")
if not EVENT_PUBLISH_URL:
    raise RuntimeError("EVENT_PUBLISH_URL environment variable not set")

BATCH_SIZE = 10
MAX_ATTEMPTS = 5


def process_events(session, events: List[Outbox]):
    for event in events:
        try:
            response = httpx.post(
                EVENT_PUBLISH_URL,
                json=event.payload,
                headers={"Idempotency-Key": str(event.event_id)},
                timeout=10,
            )
            if 200 <= response.status_code < 300:
                event.sent_at = datetime.utcnow()
                event.attempts = 0
                event.last_error = None
            else:
                event.attempts += 1
                event.last_error = f"{response.status_code} {response.text}"
        except Exception as exc:
            event.attempts += 1
            event.last_error = str(exc)
    session.commit()


def claim_events(session) -> List[Outbox]:
    stmt = (
        select(Outbox)
        .where(Outbox.sent_at.is_(None), Outbox.attempts < MAX_ATTEMPTS)
        .order_by(Outbox.occurred_at)
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    return session.scalars(stmt).all()


def worker_once():
    with get_session() as session:
        events = claim_events(session)
        if events:
            process_events(session, events)


def worker_loop():
    while True:
        with get_session() as session:
            events = claim_events(session)
            if not events:
                time.sleep(1)
                continue
            process_events(session, events)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Outbox worker")
    parser.add_argument("--once", action="store_true", help="Process a single batch and exit")
    args = parser.parse_args()
    if args.once:
        worker_once()
    else:
        worker_loop()

*** End of File