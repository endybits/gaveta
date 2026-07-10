"""The two views. Pure functions, so no argv and no stdout involved."""

import json
from datetime import datetime

import pytest

from gaveta.models import CaptureRequest
from gaveta.render import render_human, render_json

FIXED_TIME = datetime.fromisoformat("2026-07-09T14:03:11-05:00")
SPEC_EXAMPLE = "ssh -L 5432:rds-qa:5432 jump-host  # tunnel to qa database"


def _request(raw: str = "x") -> CaptureRequest:
    return CaptureRequest(raw=raw, captured_at=FIXED_TIME)


def test_human_view_reproduces_the_spec_example() -> None:
    """IMPLEMENTATION_PLAN.md Stage 1 shows this block. It is the contract."""
    expected = (
        "[gaveta] would save:\n"
        f"  raw      : {SPEC_EXAMPLE}\n"
        "  type     : unknown   (classification lands in Stage 4)\n"
        "  tags     : []\n"
        "  captured : 2026-07-09T14:03:11-05:00\n"
        "  source   : cli\n"
    )

    assert render_human(_request(SPEC_EXAMPLE)) == expected


def test_human_view_labels_the_timestamp_field_captured() -> None:
    """Display label differs from the field name `captured_at`, on purpose."""
    output = render_human(_request())

    assert "  captured : " in output
    assert "captured_at" not in output


@pytest.mark.parametrize(
    "raw",
    [
        "[bold]not bold[/bold]",
        "[unclosed",
        "[/close-only]",
        "100% [done]",
    ],
)
def test_human_view_never_interprets_user_text_as_markup(raw: str) -> None:
    """`raw` is arbitrary text. Rich markup would silently eat the brackets."""
    output = render_human(_request(raw))

    assert raw in output


def test_human_view_does_not_wrap_long_captures() -> None:
    """A long command must survive a narrow terminal intact, on one line."""
    long_raw = "ssh " + "-o VeryLongOption=value " * 20

    output = render_human(_request(long_raw.strip()))

    assert long_raw.strip() in output
    body = [line for line in output.splitlines() if line.startswith("  raw")]
    assert len(body) == 1


def test_json_view_is_one_object_with_the_five_fields() -> None:
    payload = json.loads(render_json(_request(SPEC_EXAMPLE)))

    assert payload == {
        "raw": SPEC_EXAMPLE,
        "source": "cli",
        "captured_at": "2026-07-09T14:03:11-05:00",
        "type": "unknown",
        "tags": [],
    }


def test_json_view_preserves_the_utc_offset() -> None:
    """`captured_at` is a local ISO-8601 timestamp, offset included."""
    payload = json.loads(render_json(_request()))

    assert payload["captured_at"].endswith("-05:00")


def test_json_view_emits_a_single_line() -> None:
    """One JSON object per capture, so the output stays pipeable."""
    assert "\n" not in render_json(_request()).strip()
