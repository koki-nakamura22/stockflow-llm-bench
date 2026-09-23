import argparse
import os
import uuid
import datetime
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from stockflow.db import get_session
from stockflow.models import OutboxEvent

EVENT_PUBLISH_URL = os.environ.get("EVENT_PUBLISH_URL")

def process_event(session: Session, client: httpx.Client, event_id: str):
    # We use the event_id to fetch the event in each attempt to avoid issues with expired objects
    try:
        stmt = select(OutboxEvent).where(OutboxEvent.event_id == uuid.UUID(event_id))
        event = session.execute(stmt).scalar_one()
        
        payload = {
            "event_id": str(event.event_id),
            "event_type": event.event_type,
            "aggregate_id": str(event.aggregate_id),
            "occurred_at": event.occurred_at.isoformat(),
            "payload": event.payload,
        }
        
        response = client.post(
            EVENT_PUBLISH_URL,
            json=payload,
            headers={"Idempotency-Key": str(event.event_id)},
            timeout=5.0
        )
        
        if 200 <= response.status_code < 300:
            event.sent_at = datetime.datetime.now(datetime.timezone.utc)
        else:
            event.attempts += 1
            event.last_error = f"HTTP {response.status_code}: {response.text}"
        
        session.commit()
    except Exception as e:
        session.rollback()
        # Record error in a new transaction
        with next(get_session()) as error_session:
            try:
                error_stmt = select(OutboxEvent).where(OutboxEvent.event_id == uuid.UUID(event_id))
                error_event = error_session.execute(error_stmt).scalar_one()
                error_event.attempts += 1
                error_event.last_error = str(e)
                error_session.commit()
            except:
                pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    
    if not EVENT_PUBLISH_URL:
        print("Error: EVENT_PUBLISH_URL is not set")
        return

    with httpx.Client() as client:
        if args.once:
            with next(get_session()) as session:
                stmt = (
                    select(OutboxEvent)
                    .where(OutboxEvent.sent_at.is_(None), OutboxEvent.attempts < 5)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                event = session.execute(stmt).scalar_one_or_none()
                if event:
                    process_event(session, client, str(event.event_id))
        else:
            while True:
                with next(get_session()) as session:
                    stmt = (
                        select(OutboxEvent)
                        .where(OutboxEvent.sent_at.is_(None), OutboxEvent.attempts < 5)
                        .with_for_update(skip_locked=True)
                        .limit(10)
                    )
                    events = session.execute(stmt).scalars().all()
                    if not events:
                        break
                    
                    for event in events:
                        process_event(session, client, str(event.event_id))

if __name__ == "__main__":
    main()
