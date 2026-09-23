"""contract schema: reinterpret total_amount as tax-inclusive"""
from alembic import op
import sqlalchemy as sa

revision = "0003_contract"
down_revision = "0002_expand"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # After old app stops, reinterpret total_amount as tax-inclusive
    # total_amount was tax-exclusive (subtotal), now becomes subtotal + tax
    op.execute(
        """
        UPDATE orders SET
            total_amount = subtotal_amount + tax_amount
        """
    )


def downgrade() -> None:
    # Re-interpret back: total_amount was tax-inclusive, now becomes subtotal
    # We need to derive subtotal from the previous total_amount and tax_amount
    # But tax_amount = floor(original_subtotal * 0.10), and total_amount = original_subtotal + tax_amount
    # original_subtotal = total_amount - tax_amount, but we don't have the old tax_amount separately after update
    # This is a one-way transformation; downgrade is best-effort
    op.execute(
        """
        UPDATE orders SET
            total_amount = subtotal_amount
        """
    )