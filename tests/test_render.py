"""The views over an `ItemView`. Pure functions, so no argv and no stdout involved.

The markup-safety and no-wrap invariants are inherited from Stage 1's human view and
still hold: `raw` is arbitrary user text, and a tool whose job is faithful capture must
render it faithfully.
"""

import json
from datetime import UTC, datetime

import pytest

from gaveta.db.models import ItemType
from gaveta.gate import Finding, Level, Verdict
from gaveta.models import ItemView
from gaveta.render import (
    render_blocked,
    render_item,
    render_json,
    render_json_list,
    render_list,
    render_removed,
    render_retagged,
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
        "content": None,
        "tags": [],
        "created_at": PRECISE_UTC,
        "updated_at": PRECISE_UTC,
    }
    fields.update(overrides)
    return ItemView(**fields)  # type: ignore[arg-type]


# --- render_saved / render_retagged: the confirmation line -------------------


def test_saved_names_the_id_and_type() -> None:
    assert render_saved(_view(id=42, type=ItemType.note)) == "✓ saved · id 42 · note"


def test_saved_appends_tags_when_present() -> None:
    saved = render_saved(_view(id=7, type=ItemType.command, tags=["ssh", "rds", "qa"]))

    assert saved == "✓ saved · id 7 · command · ssh, rds, qa"


def test_saved_omits_the_tags_segment_when_empty() -> None:
    assert (
        render_saved(_view(id=8, type=ItemType.note, tags=[]))
        == "✓ saved · id 8 · note"
    )


def test_saved_uses_the_enum_value_not_its_repr() -> None:
    saved = render_saved(_view(id=1, type=ItemType.command))

    assert "command" in saved
    assert "ItemType" not in saved


def test_saved_marks_a_redacted_capture() -> None:
    line = render_saved(_view(id=7, type=ItemType.link, tags=["docs"]), redacted=True)

    assert line == "✓ saved · id 7 · link · docs · redacted"


def test_saved_omits_the_marker_when_nothing_was_redacted() -> None:
    assert "redacted" not in render_saved(_view(id=7), redacted=False)


def test_retagged_uses_the_honest_verb_not_saved() -> None:
    """retag saved nothing new — the line must say so, not claim a save."""
    line = render_retagged(_view(id=7, type=ItemType.command, tags=["ssh", "rds"]))

    assert line == "✓ retagged · id 7 · command · ssh, rds"
    assert "saved" not in line


# --- render_blocked: the ✋ refusal -------------------------------------------


def test_blocked_names_the_detected_secret_and_the_escape_hatch() -> None:
    verdict = Verdict(
        level=Level.blocked,
        findings=(Finding("aws_access_key", 12, 32, "an AWS access key"),),
    )
    message = render_blocked(verdict)

    assert "blocked" in message
    assert "an AWS access key" in message  # names what was found
    assert "Secrets never enter Gaveta" in message  # states the principle
    assert "--redact" in message  # offers the escape hatch that works now


def test_blocked_falls_back_when_a_verdict_carries_no_label() -> None:
    """Defensive: a blocked verdict with no findings still produces a sane message."""
    message = render_blocked(Verdict(level=Level.blocked))

    assert "a secret" in message


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


def test_item_shows_a_dash_for_an_absent_title_content_and_tags() -> None:
    output = render_item(_view(title=None, content=None, tags=[]))

    assert "  title   : —" in output
    assert "  content : —" in output
    assert "  tags    : —" in output


def test_item_shows_the_content_when_present() -> None:
    output = render_item(_view(content="ssh rds-qa && systemctl restart pg"))

    assert "  content : ssh rds-qa && systemctl restart pg" in output


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


def test_list_prefers_the_title_over_raw_when_present() -> None:
    """The readable label the classifier gave, not the raw text, when there is one."""
    output = render_list(
        [_view("ssh -L 5432:rds:5432 jump  # tunnel", id=5, title="qa db tunnel")]
    )

    assert "qa db tunnel" in output
    assert "jump  # tunnel" not in output


def test_list_appends_tags_when_present() -> None:
    output = render_list(
        [_view("x", id=6, type=ItemType.link, tags=["docs", "sqlite"])]
    )

    assert "docs, sqlite" in output


def test_list_omits_tags_when_empty() -> None:
    output = render_list([_view("x", id=6, tags=[])]).rstrip("\n")

    assert not output.endswith("·")
    assert " · " not in output


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
