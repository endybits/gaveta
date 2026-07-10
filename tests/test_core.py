"""The core API: capture, list, get, delete, export.

Driven directly, without argv and without a subprocess. Every test runs against a real
migrated SQLite database under the per-test `GAVETA_HOME`, because the thing worth
testing is what actually lands on disk.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from gaveta import core
from gaveta.core import BlockedCapture
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


# --- the secret gate: the pipeline order is the security property ------------


def test_a_blocked_capture_raises_and_writes_nothing(session: Session) -> None:
    """A known-format secret is refused before persistence: the drawer stays empty."""
    before = len(core.list_items(session=session))

    with pytest.raises(BlockedCapture) as excinfo:
        core.capture("deploy key: AKIAIOSFODNN7EXAMPLE", session=session)

    assert excinfo.value.verdict.blocked
    assert len(core.list_items(session=session)) == before


def test_the_gate_runs_before_session_add(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gate.scan must fire before anything touches the DB — the order is the property.

    Records call order: `scan` is wrapped to append to a list, `Session.add` likewise.
    A blocked capture must have called `scan` and *never* reached `add`.
    """
    calls: list[str] = []
    real_scan = core.gate.scan

    def recording_scan(raw: str) -> object:
        calls.append("scan")
        return real_scan(raw)

    def recording_add(self: Session, obj: object, *a: object, **k: object) -> None:
        calls.append("add")

    monkeypatch.setattr(core.gate, "scan", recording_scan)
    monkeypatch.setattr(Session, "add", recording_add)

    with pytest.raises(BlockedCapture):
        core.capture("AKIAIOSFODNN7EXAMPLE", session=session)

    assert calls == ["scan"], f"expected scan and no add, got {calls}"


def test_a_redacted_blocked_capture_persists_without_the_secret(
    session: Session,
) -> None:
    """redact=True saves [REDACTED] text; the invariant is *unredacted*, not *never*."""
    view = core.capture(
        "deploy key: AKIAIOSFODNN7EXAMPLE", session=session, redact=True
    )

    assert "AKIAIOSFODNN7EXAMPLE" not in view.raw
    assert "[REDACTED]" in view.raw
    # It really landed.
    fetched = core.get_item(view.id, session=session)
    assert fetched is not None
    assert "AKIAIOSFODNN7EXAMPLE" not in fetched.raw


def test_redact_of_a_clean_capture_saves_it_unchanged(session: Session) -> None:
    """redact=True with no findings is the identity: the text is stored as typed."""
    raw = "totally normal note about lunch"
    view = core.capture(raw, session=session, redact=True)

    assert view.raw == raw


def test_a_suspicious_capture_is_not_blocked_by_the_core(session: Session) -> None:
    """Adjudicating `suspicious` needs a prompt — the core saves it; the CLI decides."""
    view = core.capture("password: MargaritaVerde2024!", session=session)

    assert view.raw == "password: MargaritaVerde2024!"


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
