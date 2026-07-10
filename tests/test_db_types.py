"""The storage invariants, asserted against a real engine rather than a declaration.

`DateTime(timezone=True)` is a no-op on SQLite, so nothing here trusts the column
declaration. Every test below writes a row and reads it back.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.dialects.sqlite import dialect as SQLiteDialect
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from gaveta.db.models import Base, Item, ItemType
from gaveta.db.types import JsonList, UtcDateTime


@pytest.fixture
def engine() -> Iterator[Engine]:
    """An in-memory database. These tests exercise column types, not migrations."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _roundtrip(engine: Engine, **kwargs: Any) -> Item:
    now = datetime.now(UTC)
    kwargs.setdefault("raw", "x")
    kwargs.setdefault("created_at", now)
    kwargs.setdefault("updated_at", now)
    with Session(engine) as session:
        session.add(Item(**kwargs))
        session.commit()
    with Session(engine) as session:
        return session.query(Item).one()


# --- UtcDateTime -------------------------------------------------------------


def test_a_naive_datetime_is_refused_not_coerced(engine: Engine) -> None:
    """The guess that a naive value means 'local' is the bug ADR-002 exists to stop.

    SQLAlchemy wraps anything a bind processor raises in `StatementError`, so the
    `ValueError` arrives as `.orig` rather than directly. That wrapping is why the
    invariant is *also* enforced in `gaveta.mapping`, where a caller can catch a plain
    `ValueError` without importing SQLAlchemy. This column is the backstop, not the
    front door — it catches whatever bypasses the mapping layer.
    """
    naive = datetime(2026, 7, 10, 8, 37, 52)

    with pytest.raises(StatementError) as exc_info:
        _roundtrip(engine, created_at=naive)

    assert isinstance(exc_info.value.orig, ValueError)
    assert "naive datetime refused" in str(exc_info.value.orig)


def test_the_bind_processor_raises_a_plain_value_error() -> None:
    """Unwrapped, so `mapping` and any future caller can rely on the type."""
    processor = UtcDateTime()

    with pytest.raises(ValueError, match="naive datetime refused"):
        processor.process_bind_param(datetime(2026, 7, 10), SQLiteDialect())


def test_a_null_datetime_passes_through_both_directions() -> None:
    """`updated_at` is NOT NULL today, but the type must not choke on NULL."""
    processor = UtcDateTime()
    dialect = SQLiteDialect()

    assert processor.process_bind_param(None, dialect) is None
    assert processor.process_result_value(None, dialect) is None


def test_an_already_utc_value_is_returned_unchanged() -> None:
    """The `tzinfo is not None` branch out, e.g. a backend that keeps the offset."""
    processor = UtcDateTime()
    aware = datetime(2026, 7, 10, 13, 37, 52, tzinfo=UTC)

    assert processor.process_result_value(aware, SQLiteDialect()) == aware


def test_an_aware_datetime_comes_back_aware_and_utc(engine: Engine) -> None:
    bogota = timezone(timedelta(hours=-5))
    local = datetime(2026, 7, 10, 8, 37, 52, tzinfo=bogota)

    restored = _roundtrip(engine, created_at=local)

    assert restored.created_at.tzinfo is UTC
    assert restored.created_at == local  # same instant
    assert restored.created_at.hour == 13  # normalized, not merely relabelled


def test_the_column_holds_utc_not_the_local_wall_clock(engine: Engine) -> None:
    """Read the raw column. This is the assertion the SQLite probe motivated."""
    bogota = timezone(timedelta(hours=-5))
    _roundtrip(engine, created_at=datetime(2026, 7, 10, 8, 37, 52, tzinfo=bogota))

    with engine.connect() as conn:
        stored = conn.execute(text("SELECT created_at FROM items")).scalar_one()

    # 08:37 in Bogota is 13:37 UTC. Storing "08:37" would be the data-loss bug.
    assert "13:37:52" in str(stored)


def test_an_instant_survives_a_timezone_change(engine: Engine) -> None:
    """Written in one zone, read in another: the drawer must not move in time.

    This is the failure mode of naive-local storage — it only appears once the user
    travels or DST rolls over, at which point the offset is already gone.
    """
    tokyo = timezone(timedelta(hours=9))
    written = datetime(2026, 7, 10, 22, 37, 52, tzinfo=tokyo)

    restored = _roundtrip(engine, created_at=written)

    assert restored.created_at == written
    assert restored.created_at.astimezone(tokyo).hour == 22


# --- JsonList ----------------------------------------------------------------


def test_tags_roundtrip_as_a_list(engine: Engine) -> None:
    restored = _roundtrip(engine, tags=["ssh", "rds", "qa"])

    assert restored.tags == ["ssh", "rds", "qa"]


def test_tags_default_to_the_empty_list(engine: Engine) -> None:
    assert _roundtrip(engine).tags == []


def test_the_tags_column_is_named_tags_json(engine: Engine) -> None:
    """Attribute `tags`, column `tags_json`. The spec names the column."""
    _roundtrip(engine, tags=["a"])

    with engine.connect() as conn:
        stored = conn.execute(text("SELECT tags_json FROM items")).scalar_one()

    assert stored == '["a"]'


def test_a_null_tags_column_reads_as_the_empty_list() -> None:
    """Defensive: a row written before the NOT NULL default, or by hand."""
    processor = JsonList()
    dialect = SQLiteDialect()

    assert processor.process_result_value(None, dialect) == []
    assert processor.process_result_value("", dialect) == []
    assert processor.process_bind_param(None, dialect) == "[]"


def test_tags_are_not_shared_between_rows(engine: Engine) -> None:
    """`default=list`, not a shared `[]` literal."""
    now = datetime.now(UTC)
    with Session(engine) as session:
        session.add_all(
            [
                Item(raw="a", created_at=now, updated_at=now),
                Item(raw="b", created_at=now, updated_at=now),
            ]
        )
        session.commit()
        first, second = session.query(Item).order_by(Item.id).all()
        first.tags.append("leaked")

        assert second.tags == []


# --- ItemType ----------------------------------------------------------------


def test_the_storage_enum_has_all_five_members() -> None:
    """Wider than the wire model's `CaptureType` from day one. ADR-002."""
    assert {t.value for t in ItemType} == {
        "link",
        "command",
        "note",
        "credential_ref",
        "unknown",
    }


def test_type_defaults_to_unknown(engine: Engine) -> None:
    assert _roundtrip(engine).type is ItemType.unknown


def test_type_roundtrips(engine: Engine) -> None:
    assert _roundtrip(engine, type=ItemType.command).type is ItemType.command


def test_repr_truncates_the_raw_text(engine: Engine) -> None:
    """A drawer holds long commands; a repr in a traceback should not hold all of it."""
    item = _roundtrip(engine, raw="x" * 200)

    rendered = repr(item)

    assert rendered.startswith("Item(id=1,")
    assert len(rendered) < 100


def test_the_type_check_constraint_exists_and_is_named(engine: Engine) -> None:
    """Read the emitted DDL, not the type object's `.name` attribute.

    `create_constraint` defaults to False in SQLAlchemy 2.0, so a model that merely
    declares `SAEnum(...)` gets a bare VARCHAR and no database-level constraint at all.
    Asserting `.name` would pass against exactly that broken schema.

    The name matters because SQLite's batch mode cannot drop an unnamed constraint, and
    Stage 4 widens this column.
    """
    ddl = str(CreateTable(Base.metadata.tables["items"]).compile(engine))

    assert "CONSTRAINT ck_items_item_type CHECK" in ddl
    assert "'credential_ref'" in ddl


def test_the_database_rejects_a_bogus_type_written_around_the_orm(
    engine: Engine,
) -> None:
    """The CHECK constraint, doing its job against raw SQL that bypasses the enum."""
    now = datetime.now(UTC).isoformat()

    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO items (raw, type, tags_json, created_at, updated_at) "
                "VALUES ('x', 'bogus', '[]', :now, :now)"
            ),
            {"now": now},
        )


def test_an_unknown_type_string_is_rejected(engine: Engine) -> None:
    """`validate_strings=True`, so a bogus value fails at write, not at read.

    Also wrapped in `StatementError`, for the same reason as the naive datetime.
    """
    with pytest.raises(StatementError) as exc_info:
        _roundtrip(engine, type="definitely-not-a-type")

    assert isinstance(exc_info.value.orig, LookupError)
