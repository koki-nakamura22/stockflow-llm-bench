"""initial schema"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("unit_price", sa.Integer(), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("unit_price >= 0", name="ck_products_price"),
        sa.CheckConstraint("stock >= 0", name="ck_products_stock"),
        sa.UniqueConstraint("tenant_id", "sku", name="uq_products_tenant_sku"),
    )
    op.create_index("ix_products_tenant_id", "products", ["tenant_id"])
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("total_amount", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("total_amount >= 0", name="ck_orders_total"),
    )
    op.create_index("ix_orders_tenant_id", "orders", ["tenant_id"])
    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE")),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id")),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("product_name", sa.String(200), nullable=False),
        sa.Column("unit_price", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("line_amount", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity"),
        sa.CheckConstraint("unit_price >= 0", name="ck_order_items_price"),
        sa.CheckConstraint("line_amount >= 0", name="ck_order_items_line"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_table(
        "outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(2000), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("attempts >= 0", name="ck_outbox_attempts"),
        sa.CheckConstraint("event_type IN ('order.created', 'order.canceled')", name="ck_outbox_event_type"),
    )
    op.create_index("ix_outbox_event_type", "outbox", ["event_type"])
    op.create_index("ix_outbox_aggregate_id", "outbox", ["aggregate_id"])


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("products")

