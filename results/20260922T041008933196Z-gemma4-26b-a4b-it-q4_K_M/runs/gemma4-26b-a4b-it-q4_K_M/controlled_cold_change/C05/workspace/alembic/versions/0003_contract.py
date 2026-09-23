"""contract order amount fields"""
from alembic import op
import sqlalchemy as sa

# revision = '0003_contract'
# down_revision = '0002_expand'

revision = "0003_contract"
down_revision = "0002_expand"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.execute("UPDATE orders SET total_amount = total_amount + tax_amount")
    op.alter_column('orders', 'subtotal_amount', nullable=False)
    op.alter_column('orders', 'tax_amount', nullable=False)

def downgrade() -> None:
    op.alter_column('orders', 'subtotal_amount', nullable=True)
    op.alter_column('orders', 'tax_amount', nullable=True)
    op.execute("UPDATE orders SET total_amount = total_amount - tax_amount")
