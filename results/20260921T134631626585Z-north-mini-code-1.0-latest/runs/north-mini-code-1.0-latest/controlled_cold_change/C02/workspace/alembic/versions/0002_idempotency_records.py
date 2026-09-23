"""Add idempotency records table for handling idempotent requests"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

revision = "0002_idempotency_records"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create idempotency_records table
    op.create_table(
        "idempotency_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scope", sa.String(512), nullable=False, index=True),
        sa.Column("original_key", sa.String(128), nullable=False),
        sa.Column("key_length", sa.Integer(), nullable=False),
        sa.Column("normalized_request_hash", sa.String(64), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("request_data", sa.Text(), nullable=False),
        sa.Column("response_data", sa.Text(), nullable=True),
    )

    # Create indexes
    op.create_index("ix_idempotency_records_scope", "idempotency_records", ["scope"])
    op.create_index("ix_idempotency_records_original_key", "idempotency_records", ["original_key"])

    # Create constraints
    op.create_check_constraint("ck_idempotency_key_length", "idempotency_records", sa.text("key_length >= 1"))
    op.create_check_constraint("ck_idempotency_key_max_length", "idempotency_records", sa.text("key_length <= 128"))


def downgrade() -> None:
    op.drop_table("idempotency_records")