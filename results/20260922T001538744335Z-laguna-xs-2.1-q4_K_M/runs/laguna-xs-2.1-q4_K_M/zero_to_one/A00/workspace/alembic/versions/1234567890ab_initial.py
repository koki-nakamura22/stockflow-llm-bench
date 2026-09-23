"""initial migration

Revision ID: 1234567890ab
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as postgresql

# revision identifiers, used by Alembic.
revision = "1234567890ab"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("sku", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("unit_price", sa.Integer(), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), onupdate=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_tenant_id", "products", ["tenant_id"])
    op.create_index("ix_products_tenant_id_sku", "products", ["tenant_id", "sku"], unique=True)

    op.create_table(
        "orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("total_amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), onupdate=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_orders_tenant_id", "orders", ["tenant_id"])

    op.create_table(
        "order_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("product_id", sa.String(length=36), nullable=False),
        sa.Column("sku", sa.String(length=255), nullable=False),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("unit_price", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("line_amount", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_table("order_items")
    op.drop_index("ix_orders_tenant_id", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_products_tenant_id_sku", table_name="products")
    op.drop_index("ix_products_tenant_id", table_name="products")
    op.drop_table("products")