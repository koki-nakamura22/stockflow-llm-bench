"""add idempotency_keys table

Revision ID: 0002_add_idempotency_keys
Revises: 0001_initial
Create Date: 2024-01-01 00:00:00.000000
"""
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
        sa.Column("id", postgresql.UUID(as_uuid=True),
                   primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                   nullable=False),
        sa.Column("scope", sa.String(256), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20),
                   nullable=False, server_default="SUCCESS"),
        sa.Column("created_at",
                   sa.DateTime(timezone=True),
                   server_default=sa.func.now()),
        sa.Column("updated_at",
                   sa.DateTime(timezone=True),
                   server_default=sa.func.now()),
        sa.CheckConstraint("key != ''",
                           name="ck_idempotency_keys_key_not_empty"),
        sa.UniqueConstraint(
             "tenant_id", "scope", "key",
            name="uq_idempotency_keys_tenant_scope_key",
         ),
     )
    op.create_index(
         "ix_idempotency_keys_tenant_id",
        "idempotency_keys",
        ["tenant_id"],
     )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
