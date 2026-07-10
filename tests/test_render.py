"""The views over an `ItemView`. Pure functions, so no argv and no stdout involved.

The markup-safety and no-wrap invariants are inherited from Stage 1's human view and
still hold: `raw` is arbitrary user text, and a tool whose job is faithful capture must
render it faithfully.
"""

import json
from datetime import UTC, datetime

import pytest

from gaveta.db.models import ItemType
from gaveta.models import ItemView
from gaveta.render import (
    render_item,
    render_json,
    render_json_list,
    render_list,
    render_removed,
    render_saved,
)

# UTC on disk; the human views convert to local. A microsecond component makes the
# second-truncation actually exercised rather than vacuously true.
PRECISE_UTC = datetime(2026, 7, 9, 19, 3, 11, 285326, tzinfo=UTC)
SPEC_EXAMPLE = "ssh -L 5432:rds-qa:5432 jump-host  # tunnel to qa database"


def _view(raw: str = "x", *, id: int = 1, **overrides: object) -> ItemView:
    fields: dict[str, object] = {
        "id": id,
        "raw": raw,
        "type": ItemType.unknown,
        "title": None,
        "tags": [],
        "created_at": PRECISE_UTC,
        "updated_at": PRECISE_UTC,
    }
    fields.update(overrides)
    return ItemView(**fields)  # type: ignore[arg-type]


# --- render_saved: the capture confirmation ----------------------------------


def test_saved_names_the_id_and_type() -> None:
    assert render_saved(_view(id=42)) == "✓ saved · id 42 · type unknown"


def test_saved_uses_the_enum_value_not_its_repr() -> None:
    saved = render_saved(_view(id=1, type=ItemType.command))

    assert "command" in saved
    assert "ItemType" not in saved


# --- render_removed: the idempotent delete message ---------------------------


def test_removed_when_the_item_existed() -> None:
    assert render_removed(7, existed=True) == "✓ removed · id 7"


def test_removed_when_the_item_was_already_absent() -> None:
    """Both are exit 0, but the message must not claim work that did not happen."""
    assert render_removed(7, existed=False) == "✓ removed · id 7 · already absent"


# --- render_item: the detail view --------------------------------------------


def test_item_labels_the_timestamp_created_not_created_at() -> None:
    """Display label differs from the field name, on purpose (ADR-001 precedent)."""
    output = render_item(_view())

    assert "  created : " in output
    assert "created_at" not in output


def test_item_renders_timestamps_in_local_time_to_the_second() -> None:
    """Stored UTC, shown local. Microseconds are noise for a human."""
    # PRECISE_UTC is 19:03:11 UTC. Whatever the runner's zone, seconds are shown and
    # microseconds are not.
    output = render_item(_view())

    assert "285326" not in output
    assert ":03:11" in output


def test_item_shows_a_dash_for_an_absent_title_and_tags() -> None:
    output = render_item(_view(title=None, tags=[]))

    assert "  title   : —" in output
    assert "  tags    : —" in output


def test_item_joins_tags_with_commas() -> None:
    output = render_item(_view(tags=["ssh", "rds", "qa"]))

    assert "ssh, rds, qa" in output


@pytest.mark.parametrize(
    "raw",
    ["[bold]not bold[/bold]", "[unclosed", "[/close-only]", "100% [done]"],
)
def test_item_never_interprets_user_text_as_markup(raw: str) -> None:
    """`raw` is arbitrary text. Rich markup would silently eat the brackets."""
    assert raw in render_item(_view(raw))


def test_item_does_not_wrap_a_long_capture() -> None:
    """A long command survives a narrow terminal intact, on one line."""
    long_raw = ("ssh " + "-o VeryLongOption=value " * 20).strip()

    output = render_item(_view(long_raw))

    raw_lines = [
        line for line in output.splitlines() if line.lstrip().startswith("raw")
    ]
    assert len(raw_lines) == 1
    assert long_raw in output


# --- render_list: the listing ------------------------------------------------


def test_list_of_an_empty_drawer_is_empty() -> None:
    """Silence, so `gaveta ls | wc -l` says zero. A 'no items' line would say one."""
    assert render_list([]) == ""


def test_list_shows_the_id_and_type_of_each_row() -> None:
    output = render_list([_view("a note", id=3, type=ItemType.note)])

    assert "3" in output
    assert "note" in output
    assert "a note" in output


def test_list_shortens_a_long_raw_to_one_line() -> None:
    long_raw = "x" * 500

    output = render_list([_view(long_raw)])

    assert "…" in output
    assert output.count("\n") == 1
    assert "x" * 500 not in output


def test_list_never_interprets_markup() -> None:
    assert "[bold]" in render_list([_view("[bold]x[/bold]")])


# --- render_json / render_json_list: the machine views -----------------------


def test_json_view_is_one_object_on_one_line() -> None:
    payload = render_json(_view(SPEC_EXAMPLE, id=42))

    assert "\n" not in payload.strip()
    assert json.loads(payload)["id"] == 42
    assert json.loads(payload)["raw"] == SPEC_EXAMPLE


def test_json_view_serializes_the_timestamp_in_utc() -> None:
    """`Z`, pydantic's spelling of UTC. Unambiguous by construction; ADR-002."""
    payload = json.loads(render_json(_view()))

    assert payload["created_at"] == "2026-07-09T19:03:11.285326Z"


def test_json_list_is_a_parseable_array() -> None:
    output = render_json_list([_view("a", id=1), _view("b", id=2)])

    parsed = json.loads(output)
    assert [item["id"] for item in parsed] == [1, 2]


def test_json_list_of_an_empty_drawer_is_an_empty_array() -> None:
    assert json.loads(render_json_list([])) == []
