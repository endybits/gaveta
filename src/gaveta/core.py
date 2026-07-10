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

from gaveta.db.models import Item, ItemType
from gaveta.mapping import now_utc, to_item, to_view
from gaveta.models import CaptureRequest, ItemView


def capture(raw: str, *, session: Session) -> ItemView:
    """Persist a capture and return it, with the id the database assigned.

    The pipeline, in order. The order is the security property.
    """
    request = CaptureRequest(raw=raw, captured_at=now_utc())

    # ─────────────────────────────────────────────────────────────────────────────
    # Stage 3 inserts the secret gate HERE:
    #
    #     verdict = gate.scan(request.raw)
    #     if verdict.blocked: ...
    #
    # It runs before `to_item`, before `session.add`, before anything reaches the
    # disk — and, from Stage 4 onward, before any model sees the text. A pipeline-
    # order test will assert exactly that against this function. Nothing that
    # touches the raw text may be added above this line.
    # ─────────────────────────────────────────────────────────────────────────────

    item = to_item(request)
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
