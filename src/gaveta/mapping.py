"""The seam between the wire contracts and the stored row.

Three models, two conversions, one file. Keeping them here rather than inside the
commands is what makes the boundary reviewable: when Stage 3 attaches a gate verdict and
Stage 4 attaches a classification, this is the diff.

See docs/adr/ADR-002-persistence-and-time.md.
"""

from datetime import UTC, datetime

from gaveta.db.models import Item, ItemType
from gaveta.models import CaptureRequest, ItemView


def now_utc() -> datetime:
    """The one clock. Aware and UTC, so it can never be refused by the column type."""
    return datetime.now(UTC)


def require_aware(moment: datetime) -> datetime:
    """Reject a naive datetime here, where a caller can catch a plain `ValueError`.

    `UtcDateTime` enforces the same rule at the column, but SQLAlchemy wraps whatever a
    bind processor raises in `StatementError`. That is a fine backstop and a poor front
    door: it surfaces at `commit()`, far from the caller, wearing the wrong type. So the
    invariant is checked twice, and this is the check that talks to people.
    """
    if moment.tzinfo is None:
        raise ValueError(
            "naive datetime refused: attach a timezone before persisting. "
            "A naive value has no instant, and guessing one silently corrupts the "
            "row the first time the clock or the timezone changes."
        )
    return moment.astimezone(UTC)


def to_item(request: CaptureRequest) -> Item:
    """A validated capture becomes an unsaved row.

    `captured_at` becomes `created_at`: the same instant, under the name the database
    and Stage 7's HTTP responses use. `source` does not cross over — it is a constant
    (`"cli"`), and persisting a constant stores nothing.

    `id` is absent by design. It is the database's to assign, and a row that could carry
    one from the wire is a row a caller could overwrite.
    """
    created = require_aware(request.captured_at)

    return Item(
        raw=request.raw,
        type=ItemType(request.type),
        title=None,
        tags=list(request.tags),
        created_at=created,
        updated_at=created,
    )


def to_view(item: Item) -> ItemView:
    """A saved row becomes the output contract.

    Called while the row's session is still open. `ItemView` holds no session, so the
    result outlives it — which is what Stage 7 needs and what a bare `Item` cannot give.
    """
    return ItemView.model_validate(item)
