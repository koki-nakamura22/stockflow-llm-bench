"""remove old total_amount column after migration is complete"""

from alembic import op
import sqlalchemy as sa

revision = "0003_remove_old_column"
down_revision = "0002_add_tax_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove the old total_amount column
    op.drop_column("orders", "total_amount")
    
    # Remove the old check constraint
    op.execute("ALTER TABLE orders DROP CONSTRAINT IF EXISTS ck_orders_total")


def downgrade() -> None:
    # Add back the old total_amount column
    op.add_column("orders", sa.Column("total_amount", sa.Integer(), nullable=False))
    
    # Add back the old check constraint
    op.create_check_constraint(
        "ck_orders_total",
        "orders",
        "total_amount >= 0"
    )