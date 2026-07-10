"""Views of a capture: terse for humans, exact for machines.

Pure functions over an `ItemView`, so both are unit-testable without touching argv or
stdout. `rich` is used here and nowhere else — it formats output and has no say in
argument parsing (ADR-001).

Timestamps render in the reader's local timezone. They are *stored* in UTC and cross the
`--json` boundary in UTC (ADR-002); converting for display is the last thing that
happens, and only for a human.
"""

import json
from datetime import datetime
from io import StringIO

from rich.console import Console

from gaveta.models import ItemView

# The detail view's labels, in display order. `created_at` is shown as `created`: the
# display label differs from the field name on purpose — the field name is the machine
# contract, this is presentation. Do not "fix" it by renaming the model field.
_LABELS: tuple[tuple[str, str], ...] = (
    ("id", "id"),
    ("raw", "raw"),
    ("type", "type"),
    ("title", "title"),
    ("tags", "tags"),
    ("created_at", "created"),
    ("updated_at", "updated"),
)

_LABEL_WIDTH = max(len(label) for _, label in _LABELS)

# How many characters of `raw` a list row shows before it is cut short. A drawer holds
# long commands; a listing that wraps them is a listing you cannot skim.
_LIST_RAW_WIDTH = 72


def _console(buffer: StringIO) -> Console:
    """A console that never rewrites the text it is given.

    `markup=False` and `highlight=False` are load-bearing, not cosmetic: `raw` is
    arbitrary user text. With markup on, a captured `[bold]x[/bold]` would print as `x`
    and lose its brackets — corruption, in a tool whose job is faithful capture.
    """
    return Console(
        file=buffer,
        markup=False,
        highlight=False,
        # Never wrap or truncate a captured command to fit a narrow terminal.
        width=10_000,
        force_terminal=False,
    )


def _local(moment: datetime) -> str:
    """UTC on disk, the reader's clock on screen. Seconds; microseconds are noise."""
    return moment.astimezone().isoformat(timespec="seconds")


def _shorten(text: str, width: int) -> str:
    """One line, at most `width` characters. Newlines would break the row alignment."""
    flattened = " ".join(text.split())
    if len(flattened) <= width:
        return flattened
    return flattened[: width - 1] + "…"


def render_json(item: ItemView) -> str:
    """The machine view: one JSON object. Field names come from the model."""
    return item.model_dump_json()


def render_json_list(items: list[ItemView]) -> str:
    """A JSON array, indented. This is `export`, and redirection is the file story."""
    return json.dumps([json.loads(item.model_dump_json()) for item in items], indent=2)


def render_saved(item: ItemView) -> str:
    """The confirmation. Capture is the hot path, and the happy path is now boring.

    Stage 1 printed five lines describing a save that never happened. It happens now, so
    the only news is the id the drawer assigned.
    """
    return f"✓ saved · id {item.id} · type {item.type.value}"


def render_removed(item_id: int, existed: bool) -> str:
    """`rm` is idempotent, and says which of the two things just happened.

    Both are successes: the postcondition (no item with this id) holds either way. But
    reporting a removal that removed nothing claims work that did not happen; a mistyped
    id deserves to show that nothing was deleted.
    """
    if existed:
        return f"✓ removed · id {item_id}"
    return f"✓ removed · id {item_id} · already absent"


def render_item(item: ItemView) -> str:
    """The detail view: every field, one per line."""
    buffer = StringIO()
    console = _console(buffer)

    for field, label in _LABELS:
        value = getattr(item, field)
        if field in ("created_at", "updated_at"):
            value = _local(value)
        elif field == "type":
            value = value.value
        elif field == "tags":
            value = ", ".join(value) if value else "—"
        elif value is None:
            value = "—"
        console.print(f"  {label:<{_LABEL_WIDTH}} : {value}")

    return buffer.getvalue()


def render_list(items: list[ItemView]) -> str:
    """The listing: one row per capture, newest first. Empty prints nothing at all.

    Silence on an empty drawer is deliberate. `gaveta ls | wc -l` should say zero, and a
    friendly "no items yet" would say one.
    """
    buffer = StringIO()
    console = _console(buffer)

    for item in items:
        raw = _shorten(item.raw, _LIST_RAW_WIDTH)
        console.print(f"  {item.id:>4}  {item.type.value:<14}  {raw}")

    return buffer.getvalue()
