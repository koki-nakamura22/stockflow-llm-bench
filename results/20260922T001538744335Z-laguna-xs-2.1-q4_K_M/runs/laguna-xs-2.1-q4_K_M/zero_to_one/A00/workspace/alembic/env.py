from __future__ import annotations

import os
from logging.config import dictConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import context

from stockflow.db.models import Base

config = context.config

# Configure logging
if config.config_file_name is not None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"generic": {"format": "%(levelname)-5.5s [%(name)s] %(message)s"}},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "generic",
                    "stream": "ext://sys.stderr",
                }
            },
            "root": {"level": "INFO", "handlers": ["console"]},
        }
    )
else:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"generic": {"format": "%(levelname)-5.5s [%(name)s] %(message)s"}},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "generic",
                    "stream": "ext://sys.stderr",
                }
            },
            "root": {"level": "INFO", "handlers": ["console"]},
        }
    )


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=Base.metadata,
        literal_binds=True,
        compare_flags={"create_column": True},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Use the config directly from the main alembic.ini
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.QueuePool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            compare_flags={"create_column": True},
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()