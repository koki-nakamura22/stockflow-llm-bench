"""idempotency key table"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

revision = "0002_idempotency_key"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("endpoint", sa.String(200), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "endpoint", "key", name="uq_idempotency_keys_tenant_endpoint_key"),
    )
    op.create_index("ix_idempotency_keys_tenant_id", "idempotency_keys", ["tenant_id"])
    op.create_index("ix_idempotency_keys_created_at", "idempotency_keys", ["created_at"])


def downgrade() -> None:
    op.drop_table("idempotency_keys")