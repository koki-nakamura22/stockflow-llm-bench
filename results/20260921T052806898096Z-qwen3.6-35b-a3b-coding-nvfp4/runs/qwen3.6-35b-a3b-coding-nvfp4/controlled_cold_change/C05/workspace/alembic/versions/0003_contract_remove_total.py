"""contract: remove old total_amount column after migration is complete"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_contract_remove_total"
down_revision = "0002_expand_tax_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
     # Remove the trigger
    op.execute("DROP TRIGGER IF EXISTS trg_sync_tax_columns ON orders")
    op.execute("DROP FUNCTION IF EXISTS sync_tax_columns()")
    
     # Remove the old total_amount column
    op.drop_column("orders", "total_amount")


def downgrade() -> None:
     # Re-add total_amount as the sum of subtotal and tax
    op.add_column("orders", sa.Column("total_amount", sa.Integer(), nullable=False, server_default="0"))
    op.execute("UPDATE orders SET total_amount = subtotal_amount + tax_amount")
