"""Add products, orders, and order_items tables.

Revision ID: 0001_initial
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
        sa.UniqueConstraint('tenant_id', 'sku', name='uq_products_tenant_sku'),
    )
    op.create_index('ix_products_tenant_id', 'products', ['tenant_id'])

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
    op.create_index('ix_orders_tenant_id', 'orders', ['tenant_id'])

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


def downgrade() -> None:
    """Drop tables."""
    op.drop_table('order_items')
    op.drop_table('orders')
    op.drop_table('products')
