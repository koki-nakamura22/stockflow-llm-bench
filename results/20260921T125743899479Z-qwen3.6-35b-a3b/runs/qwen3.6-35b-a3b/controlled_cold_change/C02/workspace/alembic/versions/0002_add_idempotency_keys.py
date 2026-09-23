"""add idempotency_keys table"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_add_idempotency_keys"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("request_body", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("status_code >= 100 AND status_code < 600", name="ck_idempotency_keys_status"),
    )
    op.create_index("ix_idempotency_keys_tenant_key", "idempotency_keys", ["tenant_id", "key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_idempotency_keys_tenant_key", table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
