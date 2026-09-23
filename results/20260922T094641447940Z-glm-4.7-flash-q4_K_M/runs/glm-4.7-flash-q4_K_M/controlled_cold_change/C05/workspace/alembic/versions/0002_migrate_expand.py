"""expand orders table with tax columns"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_migrate_expand"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns
    op.add_column("orders", sa.Column("subtotal_amount", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("tax_amount", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("total_amount_with_tax", sa.Integer(), nullable=True))

    # Backfill existing orders: calculate tax from existing total_amount
    # total_amount is pre-tax, so we need to calculate tax
    # tax = floor(total_amount * 0.10)
    # total_amount_with_tax = total_amount + tax
    op.execute(
        """
        UPDATE orders
        SET
            subtotal_amount = total_amount,
            tax_amount = floor(total_amount * 0.10),
            total_amount_with_tax = total_amount + floor(total_amount * 0.10)
        """
    )

    # Make columns NOT NULL after backfill
    op.alter_column("orders", "subtotal_amount", nullable=False)
    op.alter_column("orders", "tax_amount", nullable=False)
    op.alter_column("orders", "total_amount_with_tax", nullable=False)


def downgrade() -> None:
    # Remove new columns
    op.drop_column("orders", "total_amount_with_tax")
    op.drop_column("orders", "tax_amount")
    op.drop_column("orders", "subtotal_amount")