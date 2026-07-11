"""The core API. Every interface is a client of this module.

The CLI calls these functions today. Stage 7's FastAPI daemon and Stage 9's MCP server
will call the same ones, unchanged — "core is the product; interfaces are clients"
becomes true here, not at Stage 7. Nothing in this module knows what argv is, what a
terminal is, or how anything renders.

Every function takes an explicit `Session`. That keeps the transaction boundary the
caller's decision, and it is what lets the tests drive the core without a subprocess.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from gaveta import gate
from gaveta.brain import Classifier, make_classifier
from gaveta.db.models import Item, ItemType
from gaveta.gate import Verdict
from gaveta.mapping import now_utc, to_item, to_view
from gaveta.models import CaptureRequest, ItemView


class BlockedCapture(Exception):
    """A capture was refused because it contains a known-format secret.

    Carries the `Verdict` so the caller can name what was detected and choose an exit
    code. Raised by `capture` before anything is written; the interface (the CLI today,
    the daemon and MCP server later) translates it into a message and a return code.
    """

    def __init__(self, verdict: Verdict) -> None:
        self.verdict = verdict
        super().__init__("capture blocked: input contains a secret")


def capture(
    raw: str,
    *,
    session: Session,
    redact: bool = False,
    classifier: Classifier | None = None,
) -> ItemView:
    """Persist a capture and return it, with the id the database assigned.

    The pipeline, in order: **scan → classify → persist**. The order is the security
    property: `gate.scan` runs before the classifier, before `to_item`, before
    `session.add`, before anything reaches disk. The classifier only ever sees the
    *post-gate* text — cleared, or `[REDACTED]` — never the raw secret. That is asserted
    by the pipeline-order test on the redact path.

    `redact` is checked *before* `blocked`: `--redact` is the sanctioned way to keep a
    detected secret safely, so the `[REDACTED]` text is persisted and the raw secret is
    not. The invariant is therefore *nothing blocked reaches disk unredacted*: a blocked
    capture without redaction raises `BlockedCapture` and writes nothing, before the
    classifier runs. A `suspicious` verdict is never fatal here: adjudicating it needs a
    prompt, which is the caller's job, not the core's. See ADR-003, ADR-004.

    The classifier defaults to `make_classifier()` (Ollama with heuristic fallback). It
    is injected so tests can drive the pipeline with a fake, and so it never blocks or
    fails a capture — a classifier that cannot answer returns a heuristic guess.
    """
    request = CaptureRequest(raw=raw, captured_at=now_utc())
    classifier = classifier or make_classifier()

    verdict = gate.scan(request.raw)
    if redact:
        text = gate.redact(request.raw, verdict)
    elif verdict.blocked:
        raise BlockedCapture(verdict)
    else:
        text = request.raw

    classification = classifier.classify(text)
    item = to_item(request.model_copy(update={"raw": text}), classification)
    session.add(item)
    session.commit()
    session.refresh(item)

    return to_view(item)


def list_items(
    item_type: ItemType | None = None, *, session: Session
) -> list[ItemView]:
    """Recent captures first, optionally filtered by type.

    Ordered by `id` after `created_at`: two captures in the same clock tick is not
    hypothetical (a shell loop does it), and without the tiebreak their order would be
    whatever SQLite felt like returning.
    """
    query = select(Item).order_by(Item.created_at.desc(), Item.id.desc())
    if item_type is not None:
        query = query.where(Item.type == item_type)

    return [to_view(item) for item in session.scalars(query)]


def get_item(item_id: int, *, session: Session) -> ItemView | None:
    """One capture, or `None` if there is no such id. Absence is not an error here."""
    item = session.get(Item, item_id)
    return to_view(item) if item is not None else None


def delete_item(item_id: int, *, session: Session) -> bool:
    """Remove a capture. Returns whether there was one to remove.

    Idempotent: the postcondition — "no item with this id" — holds after every call,
    including the second. The boolean lets the caller say *what happened* without making
    the second call a failure.
    """
    item = session.get(Item, item_id)
    if item is None:
        return False

    session.delete(item)
    session.commit()
    return True


def export_items(*, session: Session) -> list[ItemView]:
    """Everything, oldest first — a backup reads as a chronology, not a feed."""
    query = select(Item).order_by(Item.created_at, Item.id)
    return [to_view(item) for item in session.scalars(query)]
