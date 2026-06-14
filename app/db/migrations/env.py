import sys
import os
import logging

from sqlalchemy import engine_from_config, pool
from alembic import context

# Make project root importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from app.db.models import Base
from app.config import settings

config = context.config

# NOTE: We intentionally do NOT call fileConfig(config.config_file_name) here.
#
# fileConfig() with its default disable_existing_loggers=True would:
#   1. Disable every logger not listed in alembic.ini (uvicorn, app.*, etc.)
#   2. Replace the app's stdout StreamHandler with alembic's stderr StreamHandler
#   3. In uvicorn --reload mode, close the root QueueHandler that forwards log
#      records to the parent process, which causes the worker to freeze/hang.
#
# Logging is already configured by app/logging_config.py before the lifespan
# runs, so alembic's migration output will flow through the existing handlers
# correctly.  The 'alembic' and 'alembic.runtime.migration' loggers are
# explicitly levelled in app/logging_config.py (WARNING / INFO respectively).

target_metadata = Base.metadata

# Use the dedicated sync URL from settings (falls back to converting the async URL).
# alembic.ini's sqlalchemy.url is intentionally NOT used at runtime — it only
# serves as a fallback for bare `alembic` CLI invocations outside the app.
sync_url = (
    settings.alembic_database_url
    or settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
)
config.set_main_option("sqlalchemy.url", sync_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()