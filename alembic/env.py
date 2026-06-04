import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

import nextcloud_todos.db
import nextcloud_todos.models  # noqa: F401 -- registers ORM tables on the metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Alembic uses a SYNC driver. The async runtime URL (sqlite+aiosqlite / asyncpg)
# is rewritten to its sync equivalent so migrations run without an event loop.
db_url = os.environ.get("DB_CONNECTION_STRING")
if db_url:
    db_url = db_url.replace("+aiosqlite", "").replace("+asyncpg", "")
    config.set_main_option("sqlalchemy.url", db_url)

target_metadata = nextcloud_todos.db.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
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
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
