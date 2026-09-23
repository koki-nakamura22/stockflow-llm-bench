"""initial

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from __future__ import annotations

import os
import sys

from alembic import op
import sqlalchemy as sa

# Add the project root to path so we can import models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'products',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('sku', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('unit_price', sa.Integer(), nullable=False),
        sa.Column('stock', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'sku', name='ix_products_tenant_sku'),
    )
    op.create_index('ix_products_tenant_id', 'products', ['tenant_id'])

    op.create_table(
        'orders',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('tenant_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('total_amount', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_orders_tenant_id', 'orders', ['tenant_id'])

    op.create_table(
        'order_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('order_id', sa.UUID(), nullable=False),
        sa.Column('product_id', sa.UUID(), nullable=False),
        sa.Column('sku', sa.String(length=100), nullable=False),
        sa.Column('product_name', sa.String(length=255), nullable=False),
        sa.Column('unit_price', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('line_amount', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['product_id'], ['products.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('order_items')
    op.drop_table('orders')
    op.drop_table('products')
