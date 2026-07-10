"""The wire contracts: `CaptureRequest` in, `ItemView` out, and their JSON Schemas.

The snapshots are the point of this file. There are two contracts because storage and
input change at different rates (ADR-002), and Stage 2 proved it: capture now returns a
saved item with an `id`, and `capture_request_schema.json` did not move.

Stage 4 widens `type`. That is a real contract change and must show up as an explicit
diff here, reviewed on purpose rather than noticed later.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from gaveta.db.models import ItemType
from gaveta.models import CaptureRequest, ItemView

SNAPSHOT_DIR = Path(__file__).parent / "__snapshots__"
CAPTURE_REQUEST_SNAPSHOT = SNAPSHOT_DIR / "capture_request_schema.json"
ITEM_VIEW_SNAPSHOT = SNAPSHOT_DIR / "item_view_schema.json"


def _strip_descriptions(node: Any) -> Any:
    """Drop every `description` key, at every depth.

    Docstrings land in the schema as `description`. Editing prose must never read as a
    contract change — and the enum `ItemView` references carries a docstring too, nested
    under `$defs`. Stripping only the top level would have made a comment edit look like
    a schema change one level down.
    """
    if isinstance(node, dict):
        return {
            key: _strip_descriptions(value)
            for key, value in node.items()
            if key != "description"
        }
    if isinstance(node, list):
        return [_strip_descriptions(item) for item in node]
    return node


def _schema(model: type[BaseModel]) -> dict[str, Any]:
    """A model's schema, minus prose that is not part of the contract."""
    stripped: dict[str, Any] = _strip_descriptions(model.model_json_schema())
    return stripped


@pytest.mark.parametrize(
    "model, snapshot",
    [
        (CaptureRequest, CAPTURE_REQUEST_SNAPSHOT),
        (ItemView, ITEM_VIEW_SNAPSHOT),
    ],
    ids=["CaptureRequest", "ItemView"],
)
def test_schema_matches_snapshot(model: type[BaseModel], snapshot: Path) -> None:
    """The machine contract is frozen. Update a snapshot deliberately, in a PR."""
    expected = json.loads(snapshot.read_text())

    assert _schema(model) == expected, (
        f"{model.__name__}'s JSON Schema changed. If that is intentional, regenerate "
        f"{snapshot.name} in the same commit and explain the change in CHANGELOG.md."
    )


@pytest.mark.parametrize(
    "snapshot",
    [CAPTURE_REQUEST_SNAPSHOT, ITEM_VIEW_SNAPSHOT],
    ids=["CaptureRequest", "ItemView"],
)
def test_snapshot_is_canonically_formatted(snapshot: Path) -> None:
    """Guard the snapshot's own formatting, so diffs stay reviewable."""
    on_disk = snapshot.read_text()
    canonical = json.dumps(json.loads(on_disk), indent=2, sort_keys=True) + "\n"

    assert on_disk == canonical


def test_no_docstring_survives_into_a_snapshot() -> None:
    """The stripper is recursive. A nested `description` would defeat the point."""
    for snapshot in (CAPTURE_REQUEST_SNAPSHOT, ITEM_VIEW_SNAPSHOT):
        assert "description" not in snapshot.read_text()


# --- CaptureRequest: the input contract, unchanged since Stage 1 --------------


def test_defaults_are_the_pre_classification_values() -> None:
    request = CaptureRequest(raw="x", captured_at=datetime.now(UTC))

    assert request.type == "unknown"
    assert request.tags == []
    assert request.source == "cli"


def test_tags_default_is_not_shared_between_instances() -> None:
    """`Field(default_factory=list)`, not a bare `[]` literal."""
    first = CaptureRequest(raw="a", captured_at=datetime.now(UTC))
    second = CaptureRequest(raw="b", captured_at=datetime.now(UTC))

    first.tags.append("leaked")

    assert second.tags == []


def test_raw_is_required() -> None:
    with pytest.raises(ValidationError):
        CaptureRequest(captured_at=datetime.now(UTC))  # type: ignore[call-arg]


@pytest.mark.parametrize("field, value", [("type", "note"), ("source", "stdin")])
def test_literal_fields_reject_later_stage_values(field: str, value: str) -> None:
    """Widening these is a Stage 4 decision, not something a caller may do."""
    kwargs: dict[str, object] = {"raw": "x", "captured_at": datetime.now(UTC)}
    kwargs[field] = value

    with pytest.raises(ValidationError):
        CaptureRequest(**kwargs)  # type: ignore[arg-type]


def test_capture_request_carries_no_storage_fields() -> None:
    """`id` and `created_at` are the database's to author, not a caller's to assert."""
    fields = set(CaptureRequest.model_fields)

    assert "id" not in fields
    assert "created_at" not in fields


def test_json_roundtrips_through_the_model() -> None:
    original = CaptureRequest(raw="ssh -L 5432", captured_at=datetime.now(UTC))

    restored = CaptureRequest.model_validate_json(original.model_dump_json())

    assert restored == original


# --- ItemView: the output contract, new in Stage 2 ---------------------------


def _view(**overrides: Any) -> ItemView:
    now = datetime.now(UTC)
    fields: dict[str, Any] = {
        "id": 1,
        "raw": "x",
        "type": ItemType.unknown,
        "title": None,
        "tags": [],
        "created_at": now,
        "updated_at": now,
    }
    return ItemView(**{**fields, **overrides})


def test_item_view_carries_the_assigned_id() -> None:
    assert _view(id=42).id == 42


def test_item_view_type_uses_the_full_storage_vocabulary() -> None:
    """Unlike `CaptureRequest`, whose `type` is `Literal["unknown"]` until Stage 4."""
    assert _view(type=ItemType.credential_ref).type is ItemType.credential_ref


def test_item_view_carries_no_source() -> None:
    """`source` is an input fact. A stored row has no use for a constant. ADR-002."""
    assert "source" not in ItemView.model_fields


def test_item_view_serializes_timestamps_in_utc() -> None:
    """`Z`, pydantic's spelling of UTC. Unambiguous; a consumer converts if it wants."""
    view = _view(created_at=datetime(2026, 7, 10, 13, 37, 52, tzinfo=UTC))

    payload = json.loads(view.model_dump_json())

    assert payload["created_at"].endswith("Z")


def test_item_view_json_roundtrips() -> None:
    original = _view(raw="ssh -L 5432", tags=["ssh", "qa"], title="tunnel")

    restored = ItemView.model_validate_json(original.model_dump_json())

    assert restored == original
