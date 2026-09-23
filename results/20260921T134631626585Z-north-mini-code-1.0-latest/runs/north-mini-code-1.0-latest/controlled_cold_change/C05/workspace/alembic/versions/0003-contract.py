"""contract: make total_amount inclusive, drop total_amount_inclusive"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None
def upgrade() -> None:
    # Overwrite total_amount with inclusive total (subtotal + tax)
    op.execute(
        "UPDATE orders SET total_amount = subtotal_amount + tax_amount"
    )
    # Drop the temporary total_amount_inclusive column
    op.drop_column("orders", "total_amount_inclusive")


def downgrade() -> None:
    # For downgrade, we need to revert total_amount to tax-exclusive (original values)
    # We need the original total_amount values; we can store them in a new column or compute from backup.
    # Since we cannot retrieve original values, we cannot fully downgrade.
    # For simplicity, we will raise an error or note that downgrade is not supported.
    raise RuntimeError("Downgrade for contract migration is not supported")