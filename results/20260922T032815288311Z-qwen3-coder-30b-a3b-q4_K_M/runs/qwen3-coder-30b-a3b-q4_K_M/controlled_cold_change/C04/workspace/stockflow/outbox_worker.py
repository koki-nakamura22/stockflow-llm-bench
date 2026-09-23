import asyncio
import json
import logging
import os
import time
from typing import Dict, Any
from uuid import UUID

import httpx
from sqlalchemy import select, update, func
from sqlalchemy.orm import Session

from stockflow.db import get_session
from stockflow.models import Base, OutboxEvent

logger = logging.getLogger(__name__)

EVENT_PUBLISH_URL = os.environ.get("EVENT_PUBLISH_URL", "http://localhost:8000/events")
MAX_ATTEMPTS = 3


class OutboxWorker:
    def __init__(self):
        self.client = httpx.AsyncClient()

    async def run_once(self):
        """Process a single batch of outbox events"""
        with get_session() as session:
            # Find unprocessed events that can be claimed
            stmt = select(OutboxEvent).where(
                OutboxEvent.sent_at.is_(None),
                OutboxEvent.attempts < MAX_ATTEMPTS,
            ).order_by(OutboxEvent.created_at)
            
            events = session.scalars(stmt).all()
            
            if not events:
                logger.info("No events to process")
                return
            
            logger.info(f"Processing {len(events)} events")
            
            for event in events:
                try:
                    await self._publish_event(session, event)
                except Exception as e:
                    logger.error(f"Failed to publish event {event.event_id}: {e}")
                    session.rollback()
    
    async def _publish_event(self, session: Session, event: OutboxEvent):
        """Publish a single event"""
        # Update the event to mark it as claimed (using optimistic locking)
        update_stmt = update(OutboxEvent).where(
            OutboxEvent.id == event.id,
            OutboxEvent.sent_at.is_(None),
        ).values(attempts=OutboxEvent.attempts + 1)
        
        result = session.execute(update_stmt)
        if result.rowcount == 0:
            # Another worker already claimed this event
            logger.info(f"Event {event.event_id} already claimed by another worker")
            return
        
        session.flush()
        
        try:
            headers = {
                "Idempotency-Key": str(event.event_id),
                "Content-Type": "application/json",
            }
            
            async with self.client.post(
                EVENT_PUBLISH_URL,
                json=event.payload,
                headers=headers,
                timeout=30.0
            ) as response:
                if 200 <= response.status < 300:
                    # Mark event as sent
                    update_sent = update(OutboxEvent).where(
                        OutboxEvent.id == event.id
                    ).values(
                        sent_at=func.now(),
                        last_error=None
                    )
                    session.execute(update_sent)
                    logger.info(f"Successfully published event {event.event_id}")
                else:
                    # Update error information
                    error_msg = f"HTTP {response.status}: {await response.text()}"
                    update_error = update(OutboxEvent).where(
                        OutboxEvent.id == event.id
                    ).values(
                        last_error=error_msg
                    )
                    session.execute(update_error)
                    logger.warning(f"Failed to publish event {event.event_id}: {error_msg}")
            
            session.commit()
        except Exception as e:
            # Update error information in case of exception
            update_error = update(OutboxEvent).where(
                OutboxEvent.id == event.id
            ).values(
                last_error=str(e)
            )
            session.execute(update_error)
            session.commit()
            raise


async def main():
    worker = OutboxWorker()
    await worker.run_once()


if __name__ == "__main__":
    asyncio.run(main())