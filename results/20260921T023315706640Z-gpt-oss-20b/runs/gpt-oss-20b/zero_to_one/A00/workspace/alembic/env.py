"""Alembic environment configuration."""
from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support.
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata

# Import database models
from stockflow import database

target_metadata = database.Base.metadata

# other values from the config, defined by the needs of env.py
# ...

# this is the database URL from alembic.ini
# but we override with env var if present
sqlalchemy_url = os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
config.set_main_option("sqlalchemy.url", sqlalchemy_url)


# this is the database engine
engine = create_engine(sqlalchemy_url, future=True)


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

    In this scenario we need to create an Engine and associate a connection
    with the context.
    """
    connectable = engine

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
