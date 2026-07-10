"""Engine and session management. The database migrates itself into existence.

There is exactly one path to a schema: `alembic upgrade head`. `create_all()` is not
called anywhere in `src/`, so the migration chain the developer writes is the migration
chain the user runs.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from alembic import command
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from gaveta.db.config import alembic_config, database_url


def _migrate_to_head() -> None:
    """Bring the drawer to the current schema. Cheap and idempotent when up to date.

    Alembic reads `alembic_version`, finds nothing to do, and returns. On a fresh
    machine this is also what creates `~/.gaveta/` and the database file itself.
    """
    command.upgrade(alembic_config(), "head")


def create_db_engine() -> Engine:
    """An engine pointed at the current `GAVETA_HOME`, with the schema guaranteed."""
    _migrate_to_head()
    return create_engine(database_url())


@contextmanager
def session() -> Iterator[Session]:
    """A session over the user's drawer, and the engine disposed when it closes.

    The engine is built per call rather than cached at import: a cached engine would
    outlive a change to `GAVETA_HOME`, and would hold a SQLite handle open for the life
    of the process. A CLI invocation runs one of these and exits.
    """
    engine = create_db_engine()
    try:
        with Session(engine) as active:
            yield active
    finally:
        engine.dispose()
