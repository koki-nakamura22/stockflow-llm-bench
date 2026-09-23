"""contract: remove subtotal_amount and tax_amount, use total_amount as tax-inclusive"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_contract_tax_columns"
down_revision = "0002_expand_tax_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # total_amount already holds subtotal_amount (tax-exclusive) from old app writes
    # We need to make total_amount = subtotal_amount + tax_amount (tax-inclusive)
    # But during compatibility, total_amount (physical) still means tax-exclusive
    # So we swap: move subtotal_amount to total_amount, then drop the others
    # Actually, after old app is stopped, total_amount should be tax-inclusive

    # First, set total_amount (physical) = subtotal_amount + tax_amount (tax-inclusive)
    op.execute("UPDATE orders SET total_amount = subtotal_amount + tax_amount")

    # Drop the intermediate columns
    op.drop_column("orders", "tax_amount")
    op.drop_column("orders", "subtotal_amount")

    # Update check constraint
    op.execute("ALTER TABLE orders DROP CONSTRAINT IF EXISTS ck_orders_total")
    op.execute("ALTER TABLE orders ADD CONSTRAINT ck_orders_total CHECK (total_amount >= 0)")


def downgrade() -> None:
    # Restore columns
    op.add_column("orders", sa.Column("subtotal_amount", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("orders", sa.Column("tax_amount", sa.Integer(), nullable=False, server_default="0"))

    # Restore old meaning: total_amount was tax-exclusive
    op.execute("UPDATE orders SET subtotal_amount = total_amount")
    op.execute("UPDATE orders SET tax_amount = FLOOR(subtotal_amount * 0.10)")
    op.execute("UPDATE orders SET total_amount = subtotal_amount")
