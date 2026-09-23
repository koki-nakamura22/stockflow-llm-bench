<%module
import os
%>
<%py
from datetime import datetime
%>
${repr(namespace)}

revision = '${revision}'
down_revision = '${down_revision}'
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}

from alembic import op
import sqlalchemy as sa

"""${message}

Revision ID: ${revision}
Revises: ${down_revision}
Create Date: ${datetime.now()}

"""

{% if up_revision %}

revision = '${revision}'
down_revision = '${down_revision}'
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}

{% endif %}

def upgrade() -> None:
    pass

def downgrade() -> None:
    pass
