"""expand order amount fields"""
from alembic import op
import sqlalchemy as sa

# revision = '0002_expand'
# down_revision = '0001_initial'

revision = "0002_expand"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('orders', sa.Column('subtotal_amount', sa.Integer(), nullable=True))
    op.add_column('orders', sa.Column('tax_amount', sa.Integer(), nullable=True))
    op.execute("UPDATE orders SET subtotal_amount = total_amount, tax_amount = floor(total_amount * 0.10)")

def downgrade() -> None:
    op.drop_column('orders', 'tax_amount')
    op.drop_column('orders', 'subtotal_amount')
