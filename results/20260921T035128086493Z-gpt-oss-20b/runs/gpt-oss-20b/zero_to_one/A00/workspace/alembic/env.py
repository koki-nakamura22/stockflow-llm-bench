"""Alembic environment configuration."""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import engine_from_config, pool
from sqlalchemy import MetaData

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
from stockflow.models import Base

target_metadata = Base.metadata

# other values from the config, if any

# this is the database URL from alembic.ini
# but we override it with env var if present
sqlalchemy_url = config.get_main_option("sqlalchemy.url")

# Override with DATABASE_URL env var if set
import os
if os.getenv("DATABASE_URL"):
    sqlalchemy_url = os.getenv("DATABASE_URL")

config.set_main_option("sqlalchemy.url", sqlalchemy_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we create an Engine and associate a connection
    with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Skip migrations if tables already exist
        result = connection.execute(sa.text("SELECT to_regclass('products')"))
        if result.scalar() is not None:
            return
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
