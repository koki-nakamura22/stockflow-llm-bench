"""add idempotency_keys table"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_add_idempotency"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(512), nullable=False),
        sa.Column("normalized_request", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("response", sa.String(2000), nullable=False),
        sa.CheckConstraint("created_at <= now()", name="ck_idempotency_created_at"),
        sa.UniqueConstraint("tenant_id", "scope", name="uq_idempotency_keys_scope"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")