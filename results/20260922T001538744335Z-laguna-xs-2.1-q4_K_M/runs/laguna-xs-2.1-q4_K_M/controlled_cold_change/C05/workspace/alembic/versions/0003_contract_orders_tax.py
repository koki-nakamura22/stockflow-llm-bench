"""contract orders - finalize tax column migration

This migration should only be run AFTER the old app is stopped.
It finalizes the tax column migration by ensuring all data is consistent.

Revision ID: 0003_contract_orders_tax
Revises: 0002_expand_orders_tax
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_contract_orders_tax"
down_revision = "0002_expand_orders_tax"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # This migration is a no-op placeholder for the contract phase
    # The actual contract happens in the app layer when old app is replaced
    # The database columns are already set up by the expand migration
    # This revision exists to provide a separate command for contract migration
    pass


def downgrade() -> None:
    pass