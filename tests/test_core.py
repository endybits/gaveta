"""The core API: capture, list, get, delete, export.

Driven directly, without argv and without a subprocess. Every test runs against a real
migrated SQLite database under the per-test `GAVETA_HOME`, because the thing worth
testing is what actually lands on disk.
"""

import inspect
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from gaveta import core
from gaveta.db.models import Item, ItemType
from gaveta.db.session import session as db_session
from gaveta.mapping import require_aware, to_item, to_view
from gaveta.models import CaptureRequest, ItemView


@pytest.fixture
def session() -> Iterator[Session]:
    with db_session() as active:
        yield active


# --- capture -----------------------------------------------------------------


def test_capture_persists_and_returns_the_saved_item(session: Session) -> None:
    view = core.capture("persist me", session=session)

    assert view.id == 1
    assert view.raw == "persist me"
    assert view.type is ItemType.unknown
    assert view.title is None
    assert view.tags == []


def test_capture_assigns_increasing_ids(session: Session) -> None:
    first = core.capture("a", session=session)
    second = core.capture("b", session=session)

    assert second.id > first.id


def test_captured_timestamps_are_aware_and_utc(session: Session) -> None:
    view = core.capture("x", session=session)

    assert view.created_at.tzinfo is not None
    assert view.created_at.utcoffset() == timedelta(0)
    assert view.created_at == view.updated_at


def test_a_crud_roundtrip_preserves_the_raw_text(session: Session) -> None:
    raw = "ssh -L 5432:rds-qa:5432 jump-host  # tunnel to qa database"

    saved = core.capture(raw, session=session)
    fetched = core.get_item(saved.id, session=session)

    assert fetched is not None
    assert fetched.raw == raw
    assert fetched == saved


# --- the Stage 3 seam --------------------------------------------------------


def test_the_gate_seam_precedes_persistence_in_capture() -> None:
    """Stage 3 inserts `gate.scan()` into `capture`, before anything is written.

    The seam is a comment today, so this asserts the *shape* Stage 3 relies on: the
    marker exists, and it sits above the first line that touches the database. When the
    gate lands, this test is replaced by a real pipeline-order assertion.
    """
    source, _ = inspect.getsourcelines(core.capture)
    body = [line.strip() for line in source]

    seam = next(
        i for i, line in enumerate(body) if "Stage 3 inserts the secret gate" in line
    )
    first_write = next(
        i for i, line in enumerate(body) if line.startswith("session.add")
    )

    assert seam < first_write, "the secret gate seam must precede persistence"


# --- list_items --------------------------------------------------------------


def test_list_items_returns_the_most_recent_first(session: Session) -> None:
    core.capture("oldest", session=session)
    core.capture("middle", session=session)
    core.capture("newest", session=session)

    assert [item.raw for item in core.list_items(session=session)] == [
        "newest",
        "middle",
        "oldest",
    ]


def test_list_items_breaks_timestamp_ties_by_id(session: Session) -> None:
    """Two captures in the same clock tick. A shell loop does this; SQLite would not
    otherwise promise an order."""
    same_instant = datetime.now(UTC)
    for raw in ("first", "second", "third"):
        session.add(Item(raw=raw, created_at=same_instant, updated_at=same_instant))
    session.commit()

    assert [item.raw for item in core.list_items(session=session)] == [
        "third",
        "second",
        "first",
    ]


def test_list_items_filters_by_type(session: Session) -> None:
    core.capture("a note", session=session)
    session.add(
        Item(
            raw="ls -la",
            type=ItemType.command,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    session.commit()

    commands = core.list_items(ItemType.command, session=session)

    assert [item.raw for item in commands] == ["ls -la"]


def test_list_items_of_an_absent_type_is_empty_not_an_error(session: Session) -> None:
    core.capture("a note", session=session)

    assert core.list_items(ItemType.link, session=session) == []


def test_list_items_on_an_empty_drawer_is_empty(session: Session) -> None:
    assert core.list_items(session=session) == []


# --- get_item ----------------------------------------------------------------


def test_get_item_of_a_missing_id_is_none(session: Session) -> None:
    """Absence is not an error in the core. The CLI decides what exit code it means."""
    assert core.get_item(999, session=session) is None


# --- delete_item -------------------------------------------------------------


def test_delete_item_removes_it_and_reports_that_it_did(session: Session) -> None:
    saved = core.capture("goodbye", session=session)

    assert core.delete_item(saved.id, session=session) is True
    assert core.get_item(saved.id, session=session) is None


def test_delete_item_is_idempotent(session: Session) -> None:
    """The postcondition holds after every call; the second call reports it did nothing.

    `gaveta rm 1 && gaveta rm 1` must not fail on the re-run.
    """
    saved = core.capture("goodbye", session=session)

    assert core.delete_item(saved.id, session=session) is True
    assert core.delete_item(saved.id, session=session) is False
    assert core.get_item(saved.id, session=session) is None


def test_delete_of_a_never_existing_id_reports_false(session: Session) -> None:
    assert core.delete_item(999, session=session) is False


# --- export_items ------------------------------------------------------------


def test_export_returns_everything_oldest_first(session: Session) -> None:
    """A backup reads as a chronology; `ls` reads as a feed."""
    core.capture("oldest", session=session)
    core.capture("newest", session=session)

    assert [item.raw for item in core.export_items(session=session)] == [
        "oldest",
        "newest",
    ]


def test_export_of_an_empty_drawer_is_empty(session: Session) -> None:
    assert core.export_items(session=session) == []


# --- mapping -----------------------------------------------------------------


def test_the_mapping_layer_rejects_a_naive_datetime_with_a_plain_value_error() -> None:
    """The front door. `UtcDateTime` is the backstop, and raises a StatementError."""
    request = CaptureRequest(raw="x", captured_at=datetime.now(UTC))
    object.__setattr__(request, "captured_at", datetime(2026, 7, 10))

    with pytest.raises(ValueError, match="naive datetime refused"):
        to_item(request)


def test_require_aware_normalizes_to_utc() -> None:
    bogota = datetime(2026, 7, 10, 8, 37, 52, tzinfo=UTC) - timedelta(hours=5)

    assert require_aware(bogota).utcoffset() == timedelta(0)


def test_source_does_not_reach_the_row(session: Session) -> None:
    """`source` is a constant. Persisting a constant stores nothing. ADR-002."""
    core.capture("x", session=session)
    item = session.get(Item, 1)

    assert item is not None
    assert not hasattr(item, "source")


def test_to_item_never_carries_an_id_from_the_wire() -> None:
    """`id` is the database's to assign, never a caller's to assert."""
    request = CaptureRequest(raw="x", captured_at=datetime.now(UTC))

    assert to_item(request).id is None


def test_to_view_survives_its_session_closing(session: Session) -> None:
    """The reason `ItemView` is not a live `Item`: Stage 7 serializes after the session.

    A bare ORM object here would raise `DetachedInstanceError` on attribute access.
    """
    core.capture("x", session=session)
    item = session.get(Item, 1)
    assert item is not None
    view = to_view(item)

    session.close()

    assert view.raw == "x"
    assert isinstance(view, ItemView)
