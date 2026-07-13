"""Views of a capture: terse for humans, exact for machines.

Pure functions over an `ItemView`, so both are unit-testable without touching argv or
stdout. `rich` is used here and nowhere else — it formats output and has no say in
argument parsing (ADR-001).

Timestamps render in the reader's local timezone. They are *stored* in UTC and cross
the `--json` boundary in UTC (ADR-002); converting for display is the last thing that
happens, and only for a human.
"""

import json
from datetime import datetime
from io import StringIO

from rich.console import Console

from gaveta.gate import Verdict
from gaveta.models import ItemView, SearchHit

# The detail view's labels, in display order. `created_at` is shown as `created`: the
# display label differs from the field name on purpose — the field name is the machine
# contract, this is presentation. Do not "fix" it by renaming the model field.
_LABELS: tuple[tuple[str, str], ...] = (
    ("id", "id"),
    ("raw", "raw"),
    ("type", "type"),
    ("title", "title"),
    ("content", "content"),
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
    arbitrary user text. With markup on, a captured `[bold]x[/bold]` would print as
    `x` and lose its brackets — corruption, in a tool whose job is faithful capture.
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


def render_saved(item: ItemView, *, verb: str = "saved", redacted: bool = False) -> str:
    """The confirmation line, one honest verb per operation.

    Capture prints `saved`; `retag` reuses this with `verb="retagged"`, because it
    saved nothing new — claiming "saved" for a reclassification is the same soft lie
    the `rm`-of-an-absent-id message avoids. The line finally earns its keep now that
    there is real classification to report:

        ✓ saved · id 7 · command · ssh, rds, qa

    The type follows the id; tags, when present, follow the type; and `· redacted` is
    appended when `--redact` rewrote the raw before storing, so the user knows the
    stored text is not what they typed. Tags are omitted entirely when empty.
    """
    tags = f" · {', '.join(item.tags)}" if item.tags else ""
    suffix = " · redacted" if redacted else ""
    return f"✓ {verb} · id {item.id} · {item.type.value}{tags}{suffix}"


def render_retagged(item: ItemView) -> str:
    """`retag`'s confirmation: the same line, the honest verb. It saved nothing new.

    A redaction marker is not composed here — `retag` re-classifies an already-stored
    item, it does not re-run the gate, so it cannot newly redact.
    """
    return render_saved(item, verb="retagged")


def render_blocked(verdict: Verdict) -> str:
    """The ✋ refusal. Names what was detected, states the rule, points to the vault.

    The vault flow (`gaveta cred --new`) lands for real in Stage 6; today the message
    names it as the upcoming path, and offers `--redact` as the escape hatch that
    works now. `verdict.findings` carries the human label the block reads back.
    """
    labels = _unique_labels(verdict)
    detected = labels[0] if labels else "a secret"
    return (
        f"✋ blocked: input contains what looks like {detected}.\n"
        "   Secrets never enter Gaveta. Store it in your vault and save a reference\n"
        "   instead — that flow lands in a later release (gaveta cred --new).\n"
        "   To keep this capture now with the secret masked:  gaveta --redact"
    )


def _unique_labels(verdict: Verdict) -> list[str]:
    """The distinct finding labels, in first-seen order. `dict` preserves insertion."""
    return list(dict.fromkeys(f.label for f in verdict.findings))


def render_removed(item_id: int, existed: bool) -> str:
    """`rm` is idempotent, and says which of the two things just happened.

    Both are successes: the postcondition (no item with this id) holds either way. But
    reporting a removal that removed nothing claims work that did not happen; a
    mistyped id deserves to show that nothing was deleted.
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

    Silence on an empty drawer is deliberate. `gaveta ls | wc -l` should say zero, and
    a friendly "no items yet" would say one.
    """
    buffer = StringIO()
    console = _console(buffer)

    for item in items:
        # The readable label when the classifier gave one, else the raw text — the
        # three-layer story on one line. Tags, when present, trail after a separator.
        label = _shorten(item.title or item.raw, _LIST_RAW_WIDTH)
        tags = f"  · {', '.join(item.tags)}" if item.tags else ""
        console.print(f"  {item.id:>4}  {item.type.value:<14}  {label}{tags}")

    return buffer.getvalue()


def render_search(hits: list[SearchHit]) -> str:
    """`gaveta f`'s hit list: id, type, title, one row each, best first.

    Mirrors `render_list`'s columns so the two read alike, but shows the `title` (the
    readable label the classifier gave) rather than a truncated raw. Empty prints
    nothing on stdout — the "no matches" notice goes to stderr, so `f | …` stays clean
    and a found-nothing search still exits 0.
    """
    buffer = StringIO()
    console = _console(buffer)

    for hit in hits:
        label = _shorten(hit.title or "", _LIST_RAW_WIDTH) or "—"
        console.print(f"  {hit.id:>4}  {hit.type.value:<14}  {label}")

    return buffer.getvalue()


def render_search_json(hits: list[SearchHit]) -> str:
    """The machine view of a search: a JSON array of hits, indented. `[]` when empty."""
    return json.dumps([json.loads(hit.model_dump_json()) for hit in hits], indent=2)


def render_copied(payload: str, *, to_clipboard: bool) -> str:
    """`f -c`'s confirmation, one line, echoing what was copied.

        ✓ copied to clipboard · ssh -L 5432:rds-qa:5432 jump

    When no clipboard backend is available (a headless machine), the same payload is
    printed under a different verb, so a script can still capture it from stdout — the
    fallback that makes `-c` usable in CI. The payload is flattened to one line.
    """
    verb = "copied to clipboard" if to_clipboard else "no clipboard · payload"
    return f"✓ {verb} · {_shorten(payload, _LIST_RAW_WIDTH)}"


def render_reindexed(embedded: int, total: int) -> str:
    """`reindex`'s confirmation: how many of the drawer's items were embedded this run.

        ✓ reindexed · embedded 3 of 28

    On a rerun with nothing new, `embedded 0 of 28` — honest that it did nothing,
    which is the idempotence guarantee showing through.
    """
    return f"✓ reindexed · embedded {embedded} of {total}"
