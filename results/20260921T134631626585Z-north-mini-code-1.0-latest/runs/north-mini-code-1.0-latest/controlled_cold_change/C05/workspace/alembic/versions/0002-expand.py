"""expand orders with subtotal_amount, tax_amount, total_amount_inclusive"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None
def upgrade() -> None:
    # Add columns with nullable=True
    op.add_column(
        "orders",
        sa.Column("subtotal_amount", sa.Integer(), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("tax_amount", sa.Integer(), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("total_amount_inclusive", sa.Integer(), nullable=True),
    )

    # Compute and backfill values for existing rows
    op.execute(
        """
        UPDATE orders
        SET
            subtotal_amount = total_amount,
            tax_amount = floor(subtotal_amount * 0.10),
            total_amount_inclusive = subtotal_amount + tax_amount
        WHERE subtotal_amount IS NULL
        """
    )

    # Set NOT NULL constraints
    with op.batch_alter_table("orders") as batch_op:
        batch_op.alter_column("subtotal_amount", nullable=False)
        batch_op.alter_column("tax_amount", nullable=False)
        batch_op.alter_column("total_amount_inclusive", nullable=False)

    # Add check constraints
    op.create_check_constraint("ck_orders_subtotal", "orders", "subtotal_amount >= 0")
    op.create_check_constraint("ck_orders_tax", "orders", "tax_amount >= 0")
    op.create_check_constraint("ck_orders_total_inclusive", "orders", "total_amount_inclusive >= 0")


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_constraint("ck_orders_total_inclusive", "orders")
        batch_op.drop_constraint("ck_orders_tax", "orders")
        batch_op.drop_constraint("ck_orders_subtotal", "orders")
        batch_op.alter_column("total_amount_inclusive", nullable=True)
        batch_op.alter_column("tax_amount", nullable=True)
        batch_op.alter_column("subtotal_amount", nullable=True)
    op.drop_column("orders", "total_amount_inclusive")
    op.drop_column("orders", "tax_amount")
    op.drop_column("orders", "subtotal_amount")