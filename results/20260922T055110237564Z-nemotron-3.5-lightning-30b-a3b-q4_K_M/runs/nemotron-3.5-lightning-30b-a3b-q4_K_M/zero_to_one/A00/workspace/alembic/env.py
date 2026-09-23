from alembic import context
from alembic.config import Config
from sqlalchemy import engine_from_config
import sys
import os

# add our model's parent directory to the path
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from stockflow.models import Base

target_metadata = Base.metadata

def run_migrations_offline() -> None:
    url = context.get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_budget=False,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(context.config_ini_section()),
        prefix="sqlalchemy.",
        target_metadata=target_metadata,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            paramstyle="named",
        )
        with context.begin_transaction():
            context.run_migrations()