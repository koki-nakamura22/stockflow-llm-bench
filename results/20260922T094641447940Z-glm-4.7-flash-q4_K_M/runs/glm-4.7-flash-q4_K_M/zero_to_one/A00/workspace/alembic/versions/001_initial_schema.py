"""Initial schema

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import uuid
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create tenants table
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # Create products table
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(50), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("unit_price", sa.Integer, nullable=False),
        sa.Column("stock", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint("stock >= 0", name="check_stock_non_negative"),
    )

    # Create orders table
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("total_amount", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # Create order_items table
    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(50), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=False),
        sa.Column("unit_price", sa.Integer, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("line_amount", sa.Integer, nullable=False),
    )

    # Create indexes
    op.create_index("ix_tenants_id", "tenants", ["id"])
    op.create_index("ix_products_tenant_id", "products", ["tenant_id"])
    op.create_index("ix_products_sku", "products", ["sku"])
    op.create_index("ix_orders_tenant_id", "orders", ["tenant_id"])
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_index("ix_order_items_product_id", "order_items", ["product_id"])

    # Create foreign keys
    op.create_foreign_key(
        "fk_products_tenant",
        "products",
        "tenants",
        ["tenant_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_orders_tenant",
        "orders",
        "tenants",
        ["tenant_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_order_items_order",
        "order_items",
        "orders",
        ["order_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_order_items_product",
        "order_items",
        "products",
        ["product_id"],
        ["id"],
    )


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_index("ix_order_items_product_id", "order_items")
    op.drop_index("ix_order_items_order_id", "order_items")
    op.drop_index("ix_orders_tenant_id", "orders")
    op.drop_index("ix_products_sku", "products")
    op.drop_index("ix_products_tenant_id", "products")
    op.drop_index("ix_tenants_id", "tenants")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("products")
    op.drop_table("tenants")