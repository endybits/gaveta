"""Migrations are the only path to a schema, and they must run from anywhere.

These drive the real Alembic `command` API against a temp database, not
`Base.metadata.create_all()`. A test that creates tables from the models proves nothing
about the migration chain the user's machine will actually run.
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from gaveta.db.config import (
    MIGRATIONS_DIR,
    alembic_config,
    database_url,
    is_search_shadow,
)
from gaveta.db.models import Base
from gaveta.paths import db_path

# The revision just before the FTS5 index landed, for the "existing rows" backfill test.
_PRE_FTS_REVISION = "e0e5bf21467f"


def _insert_item(
    connection: sa.Connection,
    *,
    raw: str,
    title: str | None = None,
    content: str | None = None,
    tags: str = "[]",
) -> None:
    """Insert one row with a plain SQL statement, bypassing the ORM.

    The migration tests deliberately avoid `Base.metadata` and the ORM: they prove what
    the *migration chain* builds, not what the models describe.
    """
    connection.execute(
        sa.text(
            "INSERT INTO items (raw, type, title, content, tags_json, "
            "created_at, updated_at) VALUES (:raw, 'note', :title, :content, :tags, "
            "'2026-01-01', '2026-01-01')"
        ),
        {"raw": raw, "title": title, "content": content, "tags": tags},
    )


def _fts_match(connection: sa.Connection, query: str) -> set[int]:
    """The set of `items.id` whose FTS row matches `query`."""
    rows = connection.execute(
        sa.text("SELECT rowid FROM items_fts WHERE items_fts MATCH :q"), {"q": query}
    ).fetchall()
    return {row[0] for row in rows}


def _tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_upgrade_creates_the_schema_from_empty() -> None:
    assert not db_path().exists()

    command.upgrade(alembic_config(), "head")

    tables = _tables(database_url())
    assert "items" in tables
    assert "alembic_version" in tables


def test_upgrade_creates_the_drawer_directory_if_it_is_missing() -> None:
    """On a fresh machine `~/.gaveta` does not exist, and SQLite will not create it.

    Without this, a user's very first `gaveta "text"` dies on `unable to open database
    file`. The tests only ever passed because `mktemp -d` had made the directory first.
    """
    home = db_path().parent
    assert not home.exists()

    command.upgrade(alembic_config(), "head")

    assert db_path().is_file()


def test_downgrade_removes_the_schema() -> None:
    config = alembic_config()
    command.upgrade(config, "head")

    command.downgrade(config, "base")

    # `alembic_version` survives a downgrade to base; the *schema* is what must go.
    assert "items" not in _tables(database_url())


def test_upgrade_downgrade_upgrade_is_green() -> None:
    """The DoD line: migrations run clean up, down, and up again."""
    config = alembic_config()

    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    assert "items" in _tables(database_url())


def test_the_migrated_schema_matches_the_orm_models() -> None:
    """No drift: what the migration builds is what the models describe.

    This is what stops the migration chain and the ORM from quietly diverging — the
    failure mode where `create_all()` works in tests and the installed CLI does not.
    """
    command.upgrade(alembic_config(), "head")

    engine = create_engine(database_url())
    try:
        with engine.connect() as connection:
            # This standalone context does NOT inherit env.py's `include_name` filter,
            # so the FTS5/vec0 virtual tables (absent from Base.metadata) must be
            # excluded here too — via the same shared predicate — or they read as drift.
            context = MigrationContext.configure(
                connection,
                opts={
                    "include_name": lambda name, type_, parent: (
                        not (
                            type_ == "table"
                            and name is not None
                            and is_search_shadow(name)
                        )
                    )
                },
            )
            diff = compare_metadata(context, Base.metadata)
    finally:
        engine.dispose()

    assert diff == [], f"schema drift between migrations and models: {diff}"


def test_content_column_is_added_and_existing_rows_survive() -> None:
    """The content migration: added nullable, and a row from before it keeps living.

    Upgrade only to the pre-content revision, insert a row the old schema knows nothing
    about `content` for, then upgrade to head. The row must survive with `content` NULL,
    the whole point of a nullable add, and the column must exist afterward.
    """
    config = alembic_config()
    command.upgrade(config, "83e1b56e69e6")  # the schema before `content`

    engine = create_engine(database_url())
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO items (raw, type, tags_json, created_at, updated_at) "
                    "VALUES ('old row', 'note', '[]', '2026-01-01', '2026-01-01')"
                )
            )
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(database_url())
    try:
        assert "content" in {c["name"] for c in inspect(engine).get_columns("items")}
        with engine.connect() as connection:
            row = connection.execute(sa.text("SELECT raw, content FROM items")).one()
    finally:
        engine.dispose()

    assert row.raw == "old row"
    assert row.content is None


def test_the_type_check_constraint_survives_the_migration() -> None:
    """Stage 4 widens this constraint, and cannot if the migration did not name it."""
    command.upgrade(alembic_config(), "head")

    engine = create_engine(database_url())
    try:
        with engine.connect() as connection:
            ddl = connection.execute(
                sa.text("SELECT sql FROM sqlite_master WHERE name = 'items'")
            ).scalar_one()
    finally:
        engine.dispose()

    assert "CONSTRAINT ck_items_item_type CHECK" in ddl


# --- The break this test exists to catch -------------------------------------


def test_migrations_resolve_from_the_package_not_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`gaveta ls` must work anywhere, and an installed wheel has no repo root.

    Placing `migrations/` at the repository root passes every test run from a checkout
    and fails for every `pipx install gaveta-cli` user. Running from a directory that is
    provably not the repo root is what distinguishes the two.
    """
    elsewhere = tmp_path / "not-the-repo"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    command.upgrade(alembic_config(), "head")

    assert "items" in _tables(database_url())


def test_the_migrations_directory_lives_inside_the_package() -> None:
    """A structural assertion, so a well-meaning move to the repo root fails loudly."""
    import gaveta.db

    package_root = Path(gaveta.db.__file__).parent

    assert package_root / "migrations" == MIGRATIONS_DIR
    assert (MIGRATIONS_DIR / "env.py").is_file()
    assert (MIGRATIONS_DIR / "script.py.mako").is_file()
    assert list(MIGRATIONS_DIR.glob("versions/*.py")), "no migration scripts found"


def test_the_database_url_follows_gaveta_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Never cached: a process that changes GAVETA_HOME must not keep the old drawer."""
    monkeypatch.setenv("GAVETA_HOME", str(tmp_path / "one"))
    first = database_url()
    monkeypatch.setenv("GAVETA_HOME", str(tmp_path / "two"))

    assert database_url() != first


# --- FTS5 keyword index ------------------------------------------------------


def test_the_fts5_migration_backfills_rows_that_already_existed() -> None:
    """The day-one bug this backfill exists to prevent.

    Triggers index *future* writes only. A drawer captured before Stage 5 must still be
    findable by the first `gaveta f` after upgrade — without needing a `reindex`, which
    heals embeddings, not the keyword index. Insert rows under the pre-FTS schema,
    upgrade to head, and the pre-existing rows must be in `items_fts`.
    """
    config = alembic_config()
    command.upgrade(config, _PRE_FTS_REVISION)

    engine = create_engine(database_url())
    try:
        with engine.begin() as connection:
            _insert_item(connection, raw="ssh tunnel to the qa database", title="qa")
            _insert_item(connection, raw="notes on the friday deploy", title="deploy")
    finally:
        engine.dispose()

    command.upgrade(config, "head")

    engine = create_engine(database_url())
    try:
        with engine.connect() as connection:
            assert _fts_match(connection, "tunnel") == {1}
            assert _fts_match(connection, "deploy") == {2}
    finally:
        engine.dispose()


def test_the_fts5_triggers_keep_the_index_in_sync_on_write() -> None:
    """Insert, update, delete on `items` must flow into `items_fts` via the triggers.

    `core.py` does plain ORM writes; the schema's triggers are what keep the keyword
    index consistent. This asserts all three arms, including that an update *purges* the
    old tokens (the failure mode of a naive sync).
    """
    command.upgrade(alembic_config(), "head")

    engine = create_engine(database_url())
    try:
        with engine.begin() as connection:
            _insert_item(connection, raw="tunnel to rds", content="ssh -L rds")
            assert _fts_match(connection, "tunnel") == {1}

            # Update: the old token ("tunnel") must vanish, the new one ("psql") appear.
            connection.execute(
                sa.text(
                    "UPDATE items SET raw = 'psql prompt', content = 'psql' "
                    "WHERE id = 1"
                )
            )
            assert _fts_match(connection, "tunnel") == set()
            assert _fts_match(connection, "psql") == {1}

            # Delete: the row leaves the index.
            connection.execute(sa.text("DELETE FROM items WHERE id = 1"))
            assert _fts_match(connection, "psql") == set()
    finally:
        engine.dispose()


def test_the_fts5_index_is_removed_on_downgrade() -> None:
    """The downgrade drops the virtual table and its triggers, leaving base schema."""
    config = alembic_config()
    command.upgrade(config, "head")
    assert "items_fts" in _tables(database_url())

    command.downgrade(config, _PRE_FTS_REVISION)

    tables = _tables(database_url())
    assert "items_fts" not in tables
    assert "items" in tables


# --- item_embeddings side table ----------------------------------------------


def test_the_item_embeddings_table_cascades_when_its_item_is_deleted() -> None:
    """One embedding per item, gone when the item is gone — the FK cascade.

    Deleting an item must not orphan its embedding row. SQLite enforces the cascade only
    when foreign keys are on, which is how the app runs; assert the behavior directly.
    """
    command.upgrade(alembic_config(), "head")

    engine = create_engine(database_url())
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("PRAGMA foreign_keys = ON"))
            _insert_item(connection, raw="a command")
            connection.execute(
                sa.text(
                    "INSERT INTO item_embeddings (item_id, model, dim, vector, "
                    "created_at) VALUES (1, 'nomic-embed-text', 3, :v, '2026-01-01')"
                ),
                {"v": b"\x00\x01\x02"},
            )
            assert (
                connection.execute(
                    sa.text("SELECT count(*) FROM item_embeddings")
                ).scalar_one()
                == 1
            )

            connection.execute(sa.text("DELETE FROM items WHERE id = 1"))

            assert (
                connection.execute(
                    sa.text("SELECT count(*) FROM item_embeddings")
                ).scalar_one()
                == 0
            )
    finally:
        engine.dispose()


def test_the_item_embeddings_table_is_removed_on_downgrade() -> None:
    """The downgrade drops the side table, leaving the FTS5 revision's schema."""
    config = alembic_config()
    command.upgrade(config, "head")
    assert "item_embeddings" in _tables(database_url())

    command.downgrade(config, "a1f2c3d4e5f6")

    assert "item_embeddings" not in _tables(database_url())
