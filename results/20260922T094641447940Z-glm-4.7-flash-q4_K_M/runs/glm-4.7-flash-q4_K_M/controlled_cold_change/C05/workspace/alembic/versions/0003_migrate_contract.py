"""contract orders table by removing old total_amount column"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_migrate_contract"
down_revision = "0002_migrate_expand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename total_amount_with_tax to total_amount (the old one is now gone)
    op.alter_column("orders", "total_amount_with_tax", new_column_name="total_amount")


def downgrade() -> None:
    # Rename back
    op.alter_column("orders", "total_amount", new_column_name="total_amount_with_tax")