"""add tax columns for rolling migration"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_add_tax_columns"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new columns for tax calculation
    op.add_column("orders", sa.Column("subtotal_amount", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("tax_amount", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("total_amount_new", sa.Integer(), nullable=True))
    
    # Add check constraints for new columns
    op.create_check_constraint(
        "ck_orders_subtotal",
        "orders",
        "subtotal_amount >= 0"
    )
    op.create_check_constraint(
        "ck_orders_tax",
        "orders",
        "tax_amount >= 0"
    )
    op.create_check_constraint(
        "ck_orders_total_new",
        "orders",
        "total_amount_new >= 0"
    )


def downgrade() -> None:
    # Remove new columns
    op.drop_column("orders", "total_amount_new")
    op.drop_column("orders", "tax_amount")
    op.drop_column("orders", "subtotal_amount")
    
    # Remove check constraints
    op.execute("ALTER TABLE orders DROP CONSTRAINT IF EXISTS ck_orders_subtotal")
    op.execute("ALTER TABLE orders DROP CONSTRAINT IF EXISTS ck_orders_tax")
    op.execute("ALTER TABLE orders DROP CONSTRAINT IF EXISTS ck_orders_total_new")