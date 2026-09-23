"""expand orders with tax columns

Revision ID: 0002_expand_orders_tax
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_expand_orders_tax"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns for tax calculation
    # subtotal_amount: pre-tax total for the order (synced from total_amount during compatibility)
    # tax_amount: calculated tax amount as floor(subtotal_amount * 0.10)
    op.add_column("orders", sa.Column("subtotal_amount", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("tax_amount", sa.Integer(), nullable=True))

    # Backfill existing rows
    # Existing total_amount is the pre-tax subtotal
    # Set subtotal_amount = total_amount (pre-tax), calculate tax
    op.execute(
        "UPDATE orders SET subtotal_amount = total_amount "
        "WHERE subtotal_amount IS NULL"
    )
    op.execute(
        "UPDATE orders SET tax_amount = FLOOR(subtotal_amount * 0.1) "
        "WHERE tax_amount IS NULL AND subtotal_amount IS NOT NULL"
    )

    # Create BEFORE trigger to keep columns in sync on writes
    # This ensures new writes from old app are reflected in new columns
    # The trigger fires BEFORE INSERT OR UPDATE on orders
    # It syncs: subtotal_amount, tax_amount based on total_amount (pre-tax)
    # 
    # Note: During compatibility, total_amount column remains pre-tax
    # New columns subtotal_amount and tax_amount are synced from it
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sync_order_tax_columns()
        RETURNS TRIGGER AS $$
        BEGIN
            -- Sync new columns when total_amount is set
            -- total_amount in old app is pre-tax subtotal
            IF NEW.total_amount IS NOT NULL THEN
                NEW.subtotal_amount = NEW.total_amount;
                NEW.tax_amount = floor(NEW.total_amount * 0.1);
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_sync_order_tax_columns
        BEFORE INSERT OR UPDATE ON orders
        FOR EACH ROW
        EXECUTE FUNCTION sync_order_tax_columns()
        """
    )

    # Make columns NOT NULL after ensuring all rows have values
    op.execute("UPDATE orders SET subtotal_amount = 0 WHERE subtotal_amount IS NULL")
    op.execute("UPDATE orders SET tax_amount = 0 WHERE tax_amount IS NULL")
    op.execute("ALTER TABLE orders ALTER COLUMN subtotal_amount SET NOT NULL")
    op.execute("ALTER TABLE orders ALTER COLUMN tax_amount SET NOT NULL")


def downgrade() -> None:
    # Drop trigger and function
    op.execute("DROP TRIGGER IF EXISTS trg_sync_order_tax_columns ON orders")
    op.execute("DROP FUNCTION IF EXISTS sync_order_tax_columns()")

    # Drop new columns
    op.drop_column("orders", "tax_amount")
    op.drop_column("orders", "subtotal_amount")