"""Engine and session management. The database migrates itself into existence.

There is exactly one path to a schema: `alembic upgrade head`. `create_all()` is not
called anywhere in `src/`, so the migration chain the developer writes is the
migration chain the user runs.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from alembic import command
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from gaveta.db.config import alembic_config, database_url

# Whether the sqlite-vec extension has ever loaded in this process. `None` until the
# first connection tries. Set by the connect listener below, read by
# `vectors_available()`. A process-level fact: the interpreter's sqlite3 either
# supports loadable extensions or it does not, and that never changes mid-run. See
# docs/adr/ADR-005-semantic-retrieval.md.
_vectors_loaded: bool | None = None


def _load_sqlite_vec(dbapi_connection: Any) -> bool:
    """Try to load sqlite-vec on a raw DBAPI connection. Returns whether it loaded.

    The extension is a native binary that loads only where the interpreter's `sqlite3`
    was built with `--enable-loadable-sqlite-extensions`. Where it was not — Homebrew
    and pyenv Pythons commonly are not, including the author's —
    `enable_load_extension` is missing entirely (`AttributeError`); where the binary
    is incompatible, the load raises `OperationalError`. Either way we degrade to
    FTS5-only, never crash.
    """
    import sqlite_vec

    try:
        dbapi_connection.enable_load_extension(True)
        sqlite_vec.load(dbapi_connection)
        dbapi_connection.enable_load_extension(False)
    except Exception:  # noqa: BLE001 — any failure means "no vectors here", not a crash
        return False
    return True


def _register_vec_loader(engine: Engine) -> None:
    """Attach a connect listener that loads sqlite-vec on every new connection.

    The single site where the extension is loaded. It updates the process-level flag
    the rest of the code reads through `vectors_available()`, so a query never has to
    probe.
    """

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        global _vectors_loaded
        _vectors_loaded = _load_sqlite_vec(dbapi_connection)


def vectors_available() -> bool:
    """Whether sqlite-vec loaded in this process. `False` until a connection tried."""
    return _vectors_loaded is True


def _migrate_to_head() -> None:
    """Bring the drawer to the current schema. Cheap and idempotent when up to date.

    Alembic reads `alembic_version`, finds nothing to do, and returns. On a fresh
    machine this is also what creates `~/.gaveta/` and the database file itself.
    """
    command.upgrade(alembic_config(), "head")


def create_db_engine() -> Engine:
    """An engine pointed at the current `GAVETA_HOME`, with the schema guaranteed.

    The vec-loader listener is attached before the schema is brought up, so every
    connection this engine hands out has sqlite-vec loaded where the platform allows
    it.
    """
    _migrate_to_head()
    engine = create_engine(database_url())
    _register_vec_loader(engine)
    return engine


@contextmanager
def session() -> Iterator[Session]:
    """A session over the user's drawer, and the engine disposed when it closes.

    The engine is built per call rather than cached at import: a cached engine would
    outlive a change to `GAVETA_HOME`, and would hold a SQLite handle open for the
    life of the process. A CLI invocation runs one of these and exits.
    """
    engine = create_db_engine()
    try:
        with Session(engine) as active:
            yield active
    finally:
        engine.dispose()
