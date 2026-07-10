"""Two views of a capture: one for humans, one for machines.

Both are pure functions over a `CaptureRequest`, so they are unit-testable without
touching argv or stdout. `rich` is used here and nowhere else — it formats output
and has no say in argument parsing (ADR-001).
"""

from io import StringIO

from rich.console import Console

from gaveta.models import CaptureRequest

# The human view's labels, in display order. `captured_at` is shown as `captured`:
# the display label deliberately differs from the field name, because the spec's
# example says `captured`. Do not "fix" this by renaming the model field — the
# field name is the machine contract, this is presentation.
_LABELS: tuple[tuple[str, str], ...] = (
    ("raw", "raw"),
    ("type", "type"),
    ("tags", "tags"),
    ("captured_at", "captured"),
    ("source", "source"),
)

_LABEL_WIDTH = max(len(label) for _, label in _LABELS)

# Stage 1 saves nothing. Say so next to the field that will change first.
_TYPE_NOTE = "(classification lands in Stage 4)"


def render_json(request: CaptureRequest) -> str:
    """The machine view: one JSON object, schema-stable.

    This is the contract later stages must honor. Field names and order come from
    the model, not from this function.
    """
    return request.model_dump_json()


def render_human(request: CaptureRequest) -> str:
    """The human view: a structured log of what *would* be saved."""
    # markup=False and highlight=False are load-bearing, not cosmetic: `raw` is
    # arbitrary user text. With markup on, capturing `[bold]x[/bold]` would print
    # `x` and silently lose the brackets — corruption in a tool whose job is
    # faithful capture. Highlighting would likewise recolor URLs and numbers.
    buffer = StringIO()
    console = Console(
        file=buffer,
        markup=False,
        highlight=False,
        # Never wrap or truncate a captured command to fit a narrow terminal.
        width=10_000,
        force_terminal=False,
    )

    console.print("[gaveta] would save:")
    for field, label in _LABELS:
        value = getattr(request, field)
        if field == "captured_at":
            # Seconds are enough for a human skimming a terminal; microseconds are
            # noise. Display only — `render_json` keeps full precision, and the
            # schema is unchanged. `timespec` rather than slicing the string,
            # which would drop the UTC offset.
            value = value.isoformat(timespec="seconds")
        elif field == "tags":
            value = list(value)
        line = f"  {label:<{_LABEL_WIDTH}} : {value}"
        if field == "type":
            line = f"{line}   {_TYPE_NOTE}"
        console.print(line)

    return buffer.getvalue()
