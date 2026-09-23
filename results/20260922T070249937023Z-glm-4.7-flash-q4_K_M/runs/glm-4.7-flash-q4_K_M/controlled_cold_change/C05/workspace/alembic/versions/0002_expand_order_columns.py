"""expand orders table to support tax calculation"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_expand_order_columns"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns with NULL initially
    op.add_column("orders", sa.Column("subtotal_amount", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("tax_amount", sa.Integer(), nullable=True))

    # Backfill existing orders with current total_amount as subtotal and calculated tax
    op.execute(
        sa.text("""
        UPDATE orders
        SET subtotal_amount = total_amount,
            tax_amount = floor(total_amount * 0.10)
        WHERE subtotal_amount IS NULL
        """)
    )

    # Set NOT NULL constraints and default values for new orders
    op.alter_column("orders", "subtotal_amount", nullable=False)
    op.alter_column("orders", "tax_amount", nullable=False)

    # Create index on subtotal_amount for potential queries
    op.create_index("ix_orders_subtotal_amount", "orders", ["subtotal_amount"])


def downgrade() -> None:
    # Remove indexes
    op.drop_index("ix_orders_subtotal_amount", "orders")

    # Remove new columns
    op.drop_column("orders", "tax_amount")
    op.drop_column("orders", "subtotal_amount")