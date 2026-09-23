"""Outbox worker for processing and publishing events."""
import argparse
import os
import sys
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from stockflow.db import SessionLocal
from stockflow.models import Outbox


EVENT_PUBLISH_URL = os.environ.get("EVENT_PUBLISH_URL", "http://event-bus:8080/events")


def process_outbox(session: Session) -> int:
    """Process one batch of pending outbox events.
    
    Returns the number of events processed.
    """
    # Claim unsent events with FOR UPDATE SKIP LOCKED
    stmt = (
        select(Outbox)
        .where(Outbox.sent_at.is_(None))
        .order_by(Outbox.created_at)
        .limit(100)
        .with_for_update(skip_locked=True)
    )
    events = session.scalars(stmt).all()
    
    if not events:
        return 0
    
    for event in events:
        # Increment attempts
        event.attempts += 1
        
        try:
            # Prepare headers with Idempotency-Key
            headers = {"Idempotency-Key": str(event.event_id)}
            
            # Prepare payload
            payload_data = {
                "event_id": str(event.event_id),
                "event_type": event.event_type,
                "aggregate_id": str(event.aggregate_id),
                "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
                "payload": event.payload,
            }
            
            response = httpx.post(
                EVENT_PUBLISH_URL,
                json=payload_data,
                headers=headers,
                timeout=30.0,
            )
            
            if 200 <= response.status_code < 300:
                # Success - mark as sent
                event.sent_at = datetime.now(timezone.utc)
                event.last_error = None
            else:
                # Failure - record error
                event.last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as e:
            event.last_error = str(e)[:200]
    
    session.commit()
    return len(events)


def main() -> int:
    """Main entry point for outbox worker."""
    parser = argparse.ArgumentParser(description="Outbox worker for processing events")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit")
    args = parser.parse_args()
    
    session = SessionLocal()
    try:
        process_outbox(session)
        return 0
    except Exception as e:
        session.rollback()
        print(f"Error processing outbox: {e}", file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())