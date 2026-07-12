"""Alembic's entry point, wired to Gaveta's own path resolution.

The database URL comes from `gaveta.db.config.database_url()`, which reads
`GAVETA_HOME`. It is deliberately *not* taken from `alembic.ini`: a URL in a config file
follows the shell's working directory, and the one thing that must never happen is a
migration running against a drawer the user did not name.

See docs/adr/ADR-002-persistence-and-time.md.
"""

from collections.abc import MutableMapping
from logging.config import fileConfig
from typing import Literal

from alembic import context
from sqlalchemy import engine_from_config, pool

from gaveta.db.config import database_url, is_search_shadow
from gaveta.db.models import Base

config = context.config

# Alembic's own parameter types for the `include_name` hook. Spelled out so the
# signature matches what `context.configure` expects under mypy --strict.
_NameType = Literal[
    "schema", "table", "column", "index", "unique_constraint", "foreign_key_constraint"
]
_ParentNames = MutableMapping[
    Literal["schema_name", "table_name", "schema_qualified_table_name"], str | None
]


def _include_name(
    name: str | None,
    type_: _NameType,
    parent_names: _ParentNames,
) -> bool:
    """Keep the FTS5/vec0 virtual tables and their shadow tables out of autogenerate.

    They are not in `Base.metadata` — `items_fts` is raw-SQL DDL and `vec_items` is a
    machine-dependent cache created outside the chain — so a comparison would forever
    report them as tables to drop. See docs/adr/ADR-005-semantic-retrieval.md.
    """
    return not (type_ == "table" and name is not None and is_search_shadow(name))


# Only when invoked through the root alembic.ini — a developer running
# `alembic revision --autogenerate`. Under `command.upgrade()` from the CLI there is no
# config file, and nothing to configure.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# GAVETA_HOME wins, always, over whatever alembic.ini may hold.
config.set_main_option("sqlalchemy.url", database_url())

# What `--autogenerate` compares the live database against.
target_metadata = Base.metadata

# SQLite cannot ALTER most things in place; batch mode copies the table, applies the
# change, and swaps it. Stage 4 widens the `type` CHECK constraint, and that migration
# is writable only with this on and the constraint named.
_BATCH = True


def run_migrations_offline() -> None:
    """Emit SQL without connecting: `alembic upgrade head --sql`."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_BATCH,
        include_name=_include_name,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect and run. This is the path `gaveta` itself takes on first use."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=_BATCH,
                include_name=_include_name,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        # `gaveta` migrates in-process on first use. A leaked engine here is a leaked
        # SQLite handle for the life of the command.
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
