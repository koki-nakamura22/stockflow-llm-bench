"""expand: add subtotal_amount and tax_amount columns"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_expand_tax_columns"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns with defaults
    op.add_column("orders", sa.Column("subtotal_amount", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("orders", sa.Column("tax_amount", sa.Integer(), nullable=False, server_default="0"))

    # Backfill existing rows: subtotal_amount = total_amount (tax-exclusive)
    op.execute("UPDATE orders SET subtotal_amount = total_amount")

    # Calculate tax_amount = floor(subtotal_amount * 0.10)
    op.execute("UPDATE orders SET tax_amount = FLOOR(subtotal_amount * 0.10)")


def downgrade() -> None:
    op.drop_column("orders", "tax_amount")
    op.drop_column("orders", "subtotal_amount")
