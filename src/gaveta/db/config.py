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
