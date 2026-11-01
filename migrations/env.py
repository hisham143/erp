
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.db import Base
from app.saas.config import get_database_url as get_app_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url():
    # Alembic-specific override is useful for isolated migration rehearsals.
    temporary_url = os.environ.get("ERP_ALEMBIC_DATABASE_URL")
    if temporary_url:
        return temporary_url

    # Otherwise use the same configured database as the application.
    # The default remains the existing local SQLite database.
    return get_app_database_url()


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(
        get_database_url(),
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
