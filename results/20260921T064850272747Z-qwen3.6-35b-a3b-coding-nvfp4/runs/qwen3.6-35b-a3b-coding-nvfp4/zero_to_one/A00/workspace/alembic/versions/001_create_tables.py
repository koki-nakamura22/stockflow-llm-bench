"""Alembic migration script for StockFlow Mini."""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    """Create tables for StockFlow Mini."""
    op.create_table(
        'products',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('sku', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('unit_price', sa.Integer(), nullable=False),
        sa.Column('stock', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'sku', name='uq_product_tenant_sku'),
    )
    op.create_index('ix_product_tenant_id', 'products', ['tenant_id'])
    op.create_index('ix_product_sku', 'products', ['sku'])

    op.create_table(
        'orders',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='PENDING'),
        sa.Column('total_amount', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_order_tenant_id', 'orders', ['tenant_id'])
    op.create_index('ix_order_status', 'orders', ['status'])

    op.create_table(
        'order_items',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('order_id', sa.Uuid(), nullable=False),
        sa.Column('product_id', sa.Uuid(), nullable=False),
        sa.Column('sku', sa.String(length=255), nullable=False),
        sa.Column('product_name', sa.String(length=255), nullable=False),
        sa.Column('unit_price', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('line_amount', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_order_item_order_id', 'order_items', ['order_id'])
    op.create_index('ix_order_item_product_id', 'order_items', ['product_id'])


def downgrade() -> None:
    """Drop tables for StockFlow Mini."""
    op.drop_table('order_items')
    op.drop_table('orders')
    op.drop_table('products')
