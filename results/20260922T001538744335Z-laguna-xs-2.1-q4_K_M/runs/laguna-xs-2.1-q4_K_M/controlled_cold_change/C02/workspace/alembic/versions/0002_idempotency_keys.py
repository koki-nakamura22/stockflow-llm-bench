"""idempotency keys table"""

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
        sa.Column("endpoint", sa.String(64), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.CheckConstraint("length(key) >= 1", name="ck_idempotency_keys_key_len"),
        sa.CheckConstraint("length(key) <= 128", name="ck_idempotency_keys_key_len_max"),
    )
    op.create_index(
        "ix_idempotency_keys_tenant_endpoint_key",
        "idempotency_keys",
        ["tenant_id", "endpoint", "key"],
        unique=True,
    )
    op.create_foreign_key(
        "fk_idempotency_keys_order",
        "idempotency_keys",
        "orders",
        ["order_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_idempotency_keys_order", "idempotency_keys", type_="foreignkey")
    op.drop_index("ix_idempotency_keys_tenant_endpoint_key", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")