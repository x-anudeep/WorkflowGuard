from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from workflowguard_api.core.config import get_settings
from workflowguard_api.db.session import Base
from workflowguard_api.models import db  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# set_main_option writes into a ConfigParser, which interpolates "%" on read -- and a
# managed Postgres password may contain one literally or as a percent-encoding, either
# of which would raise InterpolationSyntaxError here rather than at connect time.
# sqlalchemy_database_url (not the raw value) so the URL always names the psycopg driver.
config.set_main_option("sqlalchemy.url", get_settings().sqlalchemy_database_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().sqlalchemy_database_url,
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
