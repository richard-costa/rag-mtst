"""Alembic setup for offline and online database schema migrations."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Alembic configuration
# ---------------------------------------------------------------------------
# File logging and the configured migration context are initialized once here.

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# ---------------------------------------------------------------------------
# Database URL normalization
# ---------------------------------------------------------------------------
# Alembic uses SQLAlchemy's psycopg dialect while the application uses psycopg URLs.


def _sqlalchemy_url(url: str) -> str:
    """Convert a psycopg PostgreSQL URL to the SQLAlchemy dialect form.

    Args:
        url: Database URL to adapt for SQLAlchemy.

    Returns:
        SQLAlchemy-compatible database URL.
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option(
        "sqlalchemy.url", _sqlalchemy_url(database_url).replace("%", "%%")
    )

target_metadata = None


# ---------------------------------------------------------------------------
# Offline migration execution
# ---------------------------------------------------------------------------
# SQL is generated without opening a database connection in offline mode.


def run_migrations_offline() -> None:
    """Emit schema migrations as SQL without opening a database connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migration execution
# ---------------------------------------------------------------------------
# A temporary SQLAlchemy connection applies migrations to the configured database.


def run_migrations_online() -> None:
    """Apply schema migrations using a temporary database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


# ---------------------------------------------------------------------------
# Migration mode selection
# ---------------------------------------------------------------------------
# Alembic chooses SQL generation or direct execution from its runtime context.

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
