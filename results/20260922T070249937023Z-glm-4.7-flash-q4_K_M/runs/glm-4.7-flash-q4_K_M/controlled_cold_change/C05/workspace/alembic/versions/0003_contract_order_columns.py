"""remove old total_amount column after compatibility phase"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_contract_order_columns"
down_revision = "0002_expand_order_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove the old total_amount column
    # After this, total_amount will be calculated as subtotal_amount + tax_amount
    op.drop_column("orders", "total_amount")


def downgrade() -> None:
    # Add the old total_amount column back (for rollback)
    op.add_column("orders", sa.Column("total_amount", sa.Integer(), nullable=False))

    # Restore values as pre-tax total
    op.execute(
        sa.text("""
        UPDATE orders
        SET total_amount = subtotal_amount + tax_amount
        """)
    )