"""expand: add subtotal_amount and tax_amount columns

During compatibility:
- Old column `total_amount` remains (still tax-exclusive/subtotal)
- New columns `subtotal_amount` and `tax_amount` are added
- All three columns are populated on new writes
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_expand_tax_columns"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns (nullable to allow backfill)
    op.add_column("orders", sa.Column("subtotal_amount", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("tax_amount", sa.Integer(), nullable=True))

    # Backfill existing rows
    # subtotal_amount = old total_amount (tax-exclusive)
    # tax_amount = floor(subtotal_amount * 0.10)
    op.execute(
        """
        UPDATE orders
        SET subtotal_amount = total_amount,
            tax_amount = FLOOR(total_amount * 0.10)
        WHERE subtotal_amount IS NULL
        """
    )

    # Make columns non-nullable after backfill
    op.alter_column("orders", "subtotal_amount", existing_type=sa.Integer(), nullable=False)
    op.alter_column("orders", "tax_amount", existing_type=sa.Integer(), nullable=False)

    # Add new check constraints
    op.create_check_constraint(
        "ck_orders_subtotal", "orders", "subtotal_amount >= 0"
    )
    op.create_check_constraint(
        "ck_orders_tax", "orders", "tax_amount >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_orders_tax", "orders", type_="check")
    op.drop_constraint("ck_orders_subtotal", "orders", type_="check")
    op.alter_column("orders", "tax_amount", existing_type=sa.Integer(), nullable=True)
    op.alter_column("orders", "subtotal_amount", existing_type=sa.Integer(), nullable=True)
    op.drop_column("orders", "tax_amount")
    op.drop_column("orders", "subtotal_amount")
