from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from alembic.ddl.impl import DefaultImpl
from sqlalchemy import Column, MetaData, PrimaryKeyConstraint, String, Table, engine_from_config, pool

from api_gateway.config import settings
from api_gateway.metadata import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)


def _version_table_impl_with_long_revision_ids(
    self,
    *,
    version_table: str,
    version_table_schema: str | None,
    version_table_pk: bool,
    **_: object,
) -> Table:
    vt = Table(
        version_table,
        MetaData(),
        Column("version_num", String(255), nullable=False),
        schema=version_table_schema,
    )
    if version_table_pk:
        vt.append_constraint(PrimaryKeyConstraint("version_num", name=f"{version_table}_pkc"))
    return vt


DefaultImpl.version_table_impl = _version_table_impl_with_long_revision_ids

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
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
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
