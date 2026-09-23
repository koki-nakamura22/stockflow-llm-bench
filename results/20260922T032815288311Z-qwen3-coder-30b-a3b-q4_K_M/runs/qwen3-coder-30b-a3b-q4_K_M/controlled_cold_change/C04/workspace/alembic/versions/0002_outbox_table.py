"""outbox table"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_outbox_table"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text("gen_random_uuid()")),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, default=0),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_outbox_events_sent_at", "outbox_events", ["sent_at"])
    op.create_index("ix_outbox_events_attempts", "outbox_events", ["attempts"])
    op.create_index("ix_outbox_events_event_type", "outbox_events", ["event_type"])


def downgrade() -> None:
    op.drop_table("outbox_events")