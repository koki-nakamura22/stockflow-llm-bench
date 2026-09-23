"""outbox table"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_outbox"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("event_id", name="uq_outbox_event_id"),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_attempts"),
        sa.CheckConstraint("attempts <= 100", name="ck_outbox_attempts_max"),
    )
    op.create_index("ix_outbox_aggregate_id", "outbox", ["aggregate_id"])
    op.create_index("ix_outbox_sent_at", "outbox", ["sent_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_sent_at", table_name="outbox")
    op.drop_index("ix_outbox_aggregate_id", table_name="outbox")
    op.drop_table("outbox")