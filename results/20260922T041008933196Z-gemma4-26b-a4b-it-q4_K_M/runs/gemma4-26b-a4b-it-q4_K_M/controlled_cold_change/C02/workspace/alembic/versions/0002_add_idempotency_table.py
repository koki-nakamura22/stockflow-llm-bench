"""add idempotency table"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_add_idempotency_table"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint", sa.String(255), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_body", sa.String(), nullable=False),
        sa.Column("response_status_code", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "endpoint", "idempotency_key", name="uq_idempotency_records_tenant_endpoint_key"),
    )
    op.create_index("ix_idempotency_records_tenant_id", "idempotency_records", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("idempotency_records")
