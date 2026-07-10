"""The capture contract: `CaptureRequest` and its JSON Schema.

The schema snapshot is the point of this file. Stage 2 persists this model and
Stage 4 widens `type`; those are real contract changes and must show up as an
explicit diff in `tests/__snapshots__/capture_request_schema.json`, reviewed on
purpose rather than noticed later.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from gaveta.models import CaptureRequest

SNAPSHOT = Path(__file__).parent / "__snapshots__" / "capture_request_schema.json"


def _schema() -> dict[str, object]:
    """The model's schema, minus prose that is not part of the contract."""
    schema = CaptureRequest.model_json_schema()
    # The docstring lands here as "description". Editing prose must not read as a
    # contract change, so it is excluded from the snapshot on both sides.
    schema.pop("description", None)
    return schema


def test_schema_matches_snapshot() -> None:
    """The machine contract is frozen. Update the snapshot deliberately, in a PR."""
    expected = json.loads(SNAPSHOT.read_text())
    assert _schema() == expected, (
        "CaptureRequest's JSON Schema changed. If that is intentional, regenerate "
        f"{SNAPSHOT.name} in the same commit and explain the change in CHANGELOG.md."
    )


def test_snapshot_is_canonically_formatted() -> None:
    """Guard the snapshot's own formatting, so diffs stay reviewable."""
    on_disk = SNAPSHOT.read_text()
    canonical = json.dumps(json.loads(on_disk), indent=2, sort_keys=True) + "\n"
    assert on_disk == canonical


def test_defaults_are_stage_one_values() -> None:
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
def test_literal_fields_reject_stage_two_values(field: str, value: str) -> None:
    """Widening these is a Stage 4/7 decision, not something a caller may do."""
    kwargs: dict[str, object] = {"raw": "x", "captured_at": datetime.now(UTC)}
    kwargs[field] = value

    with pytest.raises(ValidationError):
        CaptureRequest(**kwargs)  # type: ignore[arg-type]


def test_json_roundtrips_through_the_model() -> None:
    """`--json` output must validate back into the model it came from."""
    original = CaptureRequest(
        raw="ssh -L 5432", captured_at=datetime.now().astimezone()
    )

    restored = CaptureRequest.model_validate_json(original.model_dump_json())

    assert restored == original
