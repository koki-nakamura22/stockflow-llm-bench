"""add outbox table for events"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer, server_default="0", nullable=False),
        sa.Column("last_error", sa.Text, nullable=True),
        # index on sent_at for efficient querying of unsent events
        sa.Index("ix_outbox_events_sent_at", "sent_at"),
        # index on event_type maybe
        sa.Index("ix_outbox_events_event_type", "event_type"),
    )

def downgrade() -> None:
    op.drop_table("outbox_events")