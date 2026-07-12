"""The one place an Alembic `Config` is built.

`script_location` is resolved from this package's own location, never from the current
working directory. Two reasons, and the second is the one that bites:

1. `gaveta ls` must work from any directory.
2. The repository root does not ship in the wheel. An installed Gaveta whose migrations
   lived at the repo root would call `command.upgrade()` against scripts that are not on
   the user's disk — a CLI that can never create its own database.

See docs/adr/ADR-002-persistence-and-time.md.
"""

from pathlib import Path

from alembic.config import Config

from gaveta.paths import db_path, ensure_home

# `Path(__file__).parent` is `gaveta/db/`, wherever that package was installed: a
# checkout, a virtualenv's site-packages, or a pipx-managed venv. It is never CWD.
MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# The virtual tables Stage 5 adds, and the shadow tables SQLite creates behind them.
# `items_fts` is a real FTS5 table created by a migration; `items_fts_data`,
# `items_fts_idx`, `items_fts_docsize`, `items_fts_config` are its SQLite-managed
# internals. `vec_items` is the sqlite-vec index, created lazily outside the migration
# chain (it exists only where the extension loads), with its own shadow tables. None of
# these are described by `Base.metadata`, so the model/migration drift check must skip
# them — a prefix match, because the shadow-table names vary across SQLite versions and
# cannot be enumerated by hand. See docs/adr/ADR-005-semantic-retrieval.md.
_SEARCH_TABLE_PREFIXES = ("items_fts", "vec_items")


def is_search_shadow(name: str) -> bool:
    """True for the FTS5/vec0 virtual tables and their SQLite-managed shadow tables.

    The one predicate shared by `env.py` (which excludes them from autogenerate) and the
    drift test (whose standalone `MigrationContext` does not inherit env.py's filter). A
    single source of truth so the two cannot diverge.
    """
    return name.startswith(_SEARCH_TABLE_PREFIXES)


def database_url() -> str:
    """The SQLite URL for the current `GAVETA_HOME`. Resolved per call, never cached.

    Caching would break the test suite's per-test `GAVETA_HOME`, and would make a
    process that changes the variable silently keep talking to the old drawer.
    """
    return f"sqlite:///{db_path()}"


def alembic_config() -> Config:
    """An Alembic config with no `alembic.ini` behind it.

    `Config()` constructs with `config_file_name = None`. The root `alembic.ini` exists
    only so `alembic revision --autogenerate` works in a checkout; nothing in `src/`
    reads it, so no one can migrate the wrong database by standing in the wrong place.

    The drawer's directory is created here. SQLite will not create a database inside a
    directory that does not exist, and on a fresh machine `~/.gaveta` never does — so a
    first-ever `gaveta "text"` would otherwise die on `unable to open database file`.
    Every path to a migration runs through this function, which is what makes it the
    right place for the one side effect.
    """
    ensure_home()

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", database_url())
    return config
