"""Alembic environment: database URL comes from ATLAS_DATABASE_URL (never hard-coded)."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from atlas import models  # noqa: F401  (register tables)
from atlas.config import get_settings
from atlas.db import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)
url = config.attributes.get("url") or get_settings().database_url
config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection") or engine_from_config(config.get_section(config.config_ini_section, {}),
                                                                           prefix="sqlalchemy.", poolclass=pool.NullPool)
    if hasattr(connectable, "connect"):
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
    else:
        context.configure(connection=connectable, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
