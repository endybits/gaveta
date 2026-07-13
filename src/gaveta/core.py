"""The core API. Every interface is a client of this module.

The CLI calls these functions today. Stage 7's FastAPI daemon and Stage 9's MCP server
will call the same ones, unchanged — "core is the product; interfaces are clients"
becomes true here, not at Stage 7. Nothing in this module knows what argv is, what a
terminal is, or how anything renders.

Every function takes an explicit `Session`. That keeps the transaction boundary the
caller's decision, and it is what lets the tests drive the core without a subprocess.
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from gaveta import gate, search
from gaveta.brain import Classifier, Embedder, make_classifier, make_embedder
from gaveta.config import EMBEDDING_DIM, load_config
from gaveta.db.models import Item, ItemEmbedding, ItemType
from gaveta.gate import Verdict
from gaveta.mapping import now_utc, to_item, to_view
from gaveta.models import CaptureRequest, ItemView
from gaveta.search import SearchResult, VectorStore


class BlockedCapture(Exception):
    """A capture was refused because it contains a known-format secret.

    Carries the `Verdict` so the caller can name what was detected and choose an exit
    code. Raised by `capture` before anything is written; the interface (the CLI
    today, the daemon and MCP server later) translates it into a message and a return
    code.
    """

    def __init__(self, verdict: Verdict) -> None:
        self.verdict = verdict
        super().__init__("capture blocked: input contains a secret")


class DimensionMismatch(Exception):
    """A reindex was refused because the model returned a wrong-width vector.

    `EMBEDDING_DIM` is baked into the vector index; a model that returns a different
    dimension cannot be stored without corrupting it. Refusing loudly is the honest
    failure — no truncation, no auto-rebuild (ADR-005). Carries the configured model,
    the returned width, and the expected width so the caller can name all three.
    """

    def __init__(self, *, model: str, got: int, expected: int) -> None:
        self.model = model
        self.got = got
        self.expected = expected
        super().__init__(
            f"embedding model {model!r} returned {got}-dim vectors, "
            f"but this drawer is built for {expected}"
        )


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
    *post-gate* text — cleared, or `[REDACTED]` — never the raw secret. That is
    asserted by the pipeline-order test on the redact path.

    `redact` is checked *before* `blocked`: `--redact` is the sanctioned way to keep a
    detected secret safely, so the `[REDACTED]` text is persisted and the raw secret
    is not. The invariant is therefore *nothing blocked reaches disk unredacted*: a
    blocked capture without redaction raises `BlockedCapture` and writes nothing,
    before the classifier runs. A `suspicious` verdict is never fatal here:
    adjudicating it needs a prompt, which is the caller's job, not the core's. See
    ADR-003, ADR-004.

    The classifier defaults to `make_classifier()` (Ollama with heuristic fallback).
    It is injected so tests can drive the pipeline with a fake, and so it never blocks
    or fails a capture — a classifier that cannot answer returns a heuristic guess.
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


def retag(
    item_id: int, *, session: Session, classifier: Classifier | None = None
) -> ItemView | None:
    """Re-classify a stored capture, or `None` if there is no such id.

    Runs the classifier over the item's `raw` — already post-gate text, since a secret
    never reached the drawer — and updates `type`, `title`, `tags`, `content`, and
    `updated_at`. This is the upgrade path for anything saved via the heuristic floor:
    capture with no model, `retag` once Ollama is up. `raw` is immutable and never
    touched; the gate does not re-run, because the stored text already passed it.

    Retag invalidates the item's embedding, but only when the *embedded text* changed.
    The recipe (`search.embedding_text`) draws on `title` and `tags`; if a retag
    changes them, the stored vector is stale, so its `item_embeddings` row is deleted
    and the next `reindex` re-embeds the item. A no-op retag (a heuristic re-run
    yielding the identical title/tags) leaves the row alone, so `retag` stays
    idempotent and does not churn embeddings. Invalidation travels with the mutation;
    `reindex` needs no staleness scan (ADR-005).
    """
    item = session.get(Item, item_id)
    if item is None:
        return None

    classifier = classifier or make_classifier()
    text_before = search.embedding_text(item)

    classification = classifier.classify(item.raw)
    item.type = classification.type
    item.title = classification.title
    item.content = classification.content
    item.tags = list(classification.tags)
    item.updated_at = now_utc()

    # Invalidate the embedding only if the embedded text changed — a no-op retag must
    # not churn it. The next reindex re-embeds a deleted row.
    if search.embedding_text(item) != text_before:
        session.execute(delete(ItemEmbedding).where(ItemEmbedding.item_id == item_id))

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
    including the second. The boolean lets the caller say *what happened* without
    making the second call a failure.
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


def find(
    query: str,
    *,
    session: Session,
    limit: int = search.DEFAULT_LIMIT,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
) -> list[SearchResult]:
    """Retrieve items by meaning, best first — the FTS5 floor fused with vectors.

    Always runs the FTS5 keyword search, which works everywhere. When a `store` is
    available (the sqlite-vec index where it loads, else an in-memory store built from
    the embeddings) and the embedder produces a query vector, a vector search runs too
    and the two rankings are fused by RRF. With no model or no vectors, `find` is
    FTS5-only — the same code path, with an empty vector ranking (ADR-005).

    `store` defaults to an in-memory store loaded from `item_embeddings`, so retrieval
    works with stored vectors even where sqlite-vec cannot load. `embedder` defaults
    to `make_embedder()`; both are injected so tests drive the whole path with fakes.
    """
    embedder = embedder or make_embedder()
    store = store if store is not None else search.load_vector_store(session)

    try:
        fts_ranked = search.fts_search(session, query, limit)
    except Exception:  # noqa: BLE001 — user text need not be valid FTS5 syntax
        # A lone `*` or an unbalanced quote is not valid FTS5; it finds nothing by
        # keyword, which is not an error.
        fts_ranked = []

    query_vector = embedder.embed(query)
    vec_ranked: list[int] = []
    if query_vector is not None:
        vec_ranked = [item_id for item_id, _ in store.search(query_vector, limit)]

    ranked = search.fuse(fts_ranked, vec_ranked)[:limit]

    results: list[SearchResult] = []
    for hit in ranked:
        item = session.get(Item, hit.item_id)
        if item is not None:  # a race could delete between ranking and load; skip it
            results.append(SearchResult(item=to_view(item), matched_on=hit.matched_on))
    return results


def reindex(
    *,
    session: Session,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
) -> tuple[int, int]:
    """Backfill embeddings for items that lack them. Returns `(embedded, total)`.

    Idempotent: an item already carrying an `item_embeddings` row is skipped, so a
    second run embeds nothing new. This is the heal path — an item captured while
    Ollama was down has no embedding and a later reindex gives it one; a retagged item
    had its row deleted, so it is missing here and gets re-embedded.

    An item whose embedder returns `None` (no model reachable) is left un-embedded for
    a future run — reindex never blocks or fails on a missing model. A model that
    returns a wrong-width vector raises `DimensionMismatch` and writes nothing: the
    dimension is baked into the index, so a mismatch is refused, not truncated
    (ADR-005).

    `store` is the vector index to also populate where one is available (the
    sqlite-vec adapter); when `None`, only `item_embeddings` is written, which is
    enough for search on a machine that rebuilds an in-memory store from it.
    """
    embedder = embedder or make_embedder()
    config = load_config()

    embedded_ids = set(session.scalars(select(ItemEmbedding.item_id)))
    all_ids = list(session.scalars(select(Item.id).order_by(Item.id)))
    embedded = 0

    for item_id in all_ids:
        if item_id in embedded_ids:
            continue
        item = session.get(Item, item_id)
        if item is None:
            continue

        vector = embedder.embed(search.embedding_text(item))
        if vector is None:
            continue  # no model — heal on a later run
        if len(vector) != EMBEDDING_DIM:
            raise DimensionMismatch(
                model=config.embedding_model,
                got=len(vector),
                expected=EMBEDDING_DIM,
            )

        session.add(
            ItemEmbedding(
                item_id=item_id,
                model=config.embedding_model,
                dim=len(vector),
                vector=search.serialize_vector(vector),
                created_at=now_utc(),
            )
        )
        if store is not None:
            store.upsert(item_id, vector)
        embedded += 1

    session.commit()
    return embedded, len(all_ids)
