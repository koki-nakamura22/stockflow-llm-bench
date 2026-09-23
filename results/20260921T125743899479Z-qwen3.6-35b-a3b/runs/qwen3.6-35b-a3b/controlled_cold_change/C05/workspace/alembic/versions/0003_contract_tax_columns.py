"""contract: replace total_amount with tax-inclusive version

After old app is stopped:
- Old `total_amount` column (tax-exclusive) is dropped
- New `total_amount` column = subtotal_amount + tax_amount (tax-inclusive)
- Only new columns are written by the app
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_contract_tax_columns"
down_revision = "0002_expand_tax_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old check constraint on total_amount
    op.drop_constraint("ck_orders_total", "orders", type_="check")

    # Drop old total_amount column (tax-exclusive)
    op.drop_column("orders", "total_amount")

    # Add new total_amount column (tax-inclusive) with computed default
    op.add_column(
        "orders",
        sa.Column(
            "total_amount",
            sa.Integer(),
            server_default=sa.text("subtotal_amount + tax_amount"),
            nullable=False,
        ),
    )

    # Backfill existing rows where total_amount is NULL
    op.execute(
        """
        UPDATE orders
        SET total_amount = subtotal_amount + tax_amount
        WHERE total_amount IS NULL
        """
    )

    # Add new check constraint
    op.create_check_constraint(
        "ck_orders_total", "orders", "total_amount >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_orders_total", "orders", type_="check")
    op.drop_column("orders", "total_amount")
    op.add_column(
        "orders",
        sa.Column("total_amount", sa.Integer(), nullable=False),
    )
    op.create_check_constraint(
        "ck_orders_total", "orders", "total_amount >= 0"
    )
