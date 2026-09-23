"""idempotency keys table"""

from alembic import op
import sqlalchemy as sa
import uuid


revision = "0002_idempotency_keys"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Uuid(), primary_key=True, default=uuid.uuid4),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("normalized_request", sa.String(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "key", name="uq_idempotency_keys_tenant_key"),
    )
    op.create_index(
        "ix_idempotency_keys_tenant_key", "idempotency_keys", ["tenant_id", "key"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_tenant_key", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")