"""Initial migration script.

This script creates the tables defined in stockflow.models.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("sku", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("unit_price", sa.Integer, nullable=False),
        sa.Column("stock", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "sku", name="uq_tenant_sku"),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("total_amount", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_table(
        "order_items",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("order_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("product_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("sku", sa.String(length=255), nullable=False),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("unit_price", sa.Integer, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("line_amount", sa.Integer, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("products")
