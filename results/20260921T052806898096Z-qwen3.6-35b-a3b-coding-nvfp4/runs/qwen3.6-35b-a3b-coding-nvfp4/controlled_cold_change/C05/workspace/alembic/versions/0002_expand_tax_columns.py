"""expand: add subtotal_amount and tax_amount columns"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from math import floor

revision = "0002_expand_tax_columns"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns
    op.add_column("orders", sa.Column("subtotal_amount", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("orders", sa.Column("tax_amount", sa.Integer(), nullable=False, server_default="0"))
    
    # Backfill: subtotal_amount = old total_amount (tax-exclusive)
    op.execute("UPDATE orders SET subtotal_amount = total_amount")
    
    # Backfill: tax_amount = floor(subtotal_amount * 0.10)
    op.execute("UPDATE orders SET tax_amount = floor(subtotal_amount * 0.10)")
    
    # Create trigger to keep subtotal_amount and tax_amount in sync when total_amount changes
    # This handles old app writes to total_amount
    op.execute("""
        CREATE OR REPLACE FUNCTION sync_tax_columns()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.subtotal_amount := NEW.total_amount;
            NEW.tax_amount := floor(NEW.total_amount * 0.10);
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_sync_tax_columns
        BEFORE UPDATE ON orders
        FOR EACH ROW
        WHEN (OLD.subtotal_amount IS DISTINCT FROM NEW.subtotal_amount OR
              OLD.tax_amount IS DISTINCT FROM NEW.tax_amount)
        EXECUTE FUNCTION sync_tax_columns()
    """)


def downgrade() -> None:
    op.drop_column("orders", "tax_amount")
    op.drop_column("orders", "subtotal_amount")
