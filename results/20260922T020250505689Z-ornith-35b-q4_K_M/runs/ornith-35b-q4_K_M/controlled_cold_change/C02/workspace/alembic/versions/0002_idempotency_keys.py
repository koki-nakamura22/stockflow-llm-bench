"""add idempotency_keys table"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_idempotency_keys"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(128), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result_status", sa.Integer(), nullable=True),
        sa.Column("result_body", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('PENDING', 'SUCCESS', 'FAILURE')", name="ck_idempotency_keys_status"),
        sa.UniqueConstraint("tenant_id", "endpoint", "idempotency_key", name="uq_idempotency_keys_scope"),
    )
    op.create_index("ix_idempotency_keys_tenant_id", "idempotency_keys", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("idempotency_keys")
