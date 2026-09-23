"""expand schema with subtotal and tax columns"""
from alembic import op
import sqlalchemy as sa

revision = "0002_expand"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns for tax breakdown
    op.add_column("orders", sa.Column("subtotal_amount", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("tax_amount", sa.Integer(), nullable=True))

    # Backfill existing orders: calculate subtotal from order_items
    op.execute(
        """
        UPDATE orders SET
            subtotal_amount = COALESCE(
                (SELECT SUM(line_amount)
                 FROM order_items
                 WHERE order_items.order_id = orders.id), 0
            ),
            tax_amount = FLOOR(subtotal_amount * 0.10)
        """
    )

    # Make columns non-nullable with default 0
    op.alter_column("orders", "subtotal_amount", nullable=False, server_default="0")
    op.alter_column("orders", "tax_amount", nullable=False, server_default="0")


def downgrade() -> None:
    op.alter_column("orders", "subtotal_amount", nullable=True)
    op.alter_column("orders", "tax_amount", nullable=True)
    op.drop_column("orders", "tax_amount")
    op.drop_column("orders", "subtotal_amount")