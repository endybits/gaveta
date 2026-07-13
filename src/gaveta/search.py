"""Semantic retrieval: the FTS5 floor, the vector enhancement, and their fusion.

Stage 5's retrieval logic, kept out of `core.py` so the ranking is unit-testable
without a database and independent of any interface. Three pieces, in order of how
much of the interesting logic they hold:

- `fuse(fts_ranked, vec_ranked)` — pure Reciprocal Rank Fusion over two ordered
  id-lists. When vectors are unavailable (the extension will not load) or Ollama is
  down at search time, `vec_ranked` is `[]` and fusion reduces to FTS5 order. One
  ranking path with a possibly-empty second input, not two branches. This is where
  fusion is proven in tests, with no store at all.

- `VectorStore` — the seam over the vector index. `InMemoryVectorStore` (here) is pure
  Python cosine over the stored blobs, used in every test and where sqlite-vec cannot
  load; `Vec0Store` (added later) is the sqlite-vec adapter, used where it can.

- `embedding_text(item)` and the float32 blob (de)serialization — what gets embedded,
  and the one encoding shared by the `item_embeddings` table and the vec index.

See docs/adr/ADR-005-semantic-retrieval.md.
"""

import struct
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from gaveta.db.models import Item, ItemEmbedding
from gaveta.models import ItemView

# The RRF constant. `k = 60` is the value from the original RRF paper (Cormack et
# al.); it damps low ranks so the top of each list dominates without any one list
# winning outright.
_RRF_K = 60

# How many hits a search returns. A drawer is browsed, not paged; a short list is the
# product. The CLI and the wire model surface exactly these.
DEFAULT_LIMIT = 10


class MatchedOn(StrEnum):
    """Which retrieval source surfaced a hit — deterministic, unlike a raw score.

    A hit found by both keyword and vector search ranks higher (fusion), but what the
    wire reports is *how* it was found, not a machine-dependent float. `semantic` and
    `both` only ever appear where the vector index is available.
    """

    keyword = "keyword"
    semantic = "semantic"
    both = "both"


@dataclass(frozen=True)
class Ranked:
    """One fused result: an item id and how it was matched."""

    item_id: int
    matched_on: MatchedOn


def fuse(fts_ranked: list[int], vec_ranked: list[int]) -> list[Ranked]:
    """Combine a keyword ranking and a vector ranking by Reciprocal Rank Fusion.

    Each list is item ids in descending relevance. An item's fused score is the sum,
    over the lists it appears in, of `1 / (k + rank)` — `rank` its 0-based position.
    Items come back in descending fused score, tagged with which source(s) found them.

    The vector list may be empty — no model, or no loadable extension — and then this
    is exactly the FTS5 order, every hit `keyword`. The degraded path, expressed as
    data rather than a branch.
    """
    scores: dict[int, float] = {}
    in_fts: set[int] = set()
    in_vec: set[int] = set()

    for rank, item_id in enumerate(fts_ranked):
        scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (_RRF_K + rank)
        in_fts.add(item_id)
    for rank, item_id in enumerate(vec_ranked):
        scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (_RRF_K + rank)
        in_vec.add(item_id)

    def matched(item_id: int) -> MatchedOn:
        if item_id in in_fts and item_id in in_vec:
            return MatchedOn.both
        if item_id in in_vec:
            return MatchedOn.semantic
        return MatchedOn.keyword

    # Sort by score descending; break ties by id ascending so the order is
    # deterministic (equal scores would otherwise follow dict iteration order).
    ordered = sorted(scores, key=lambda item_id: (-scores[item_id], item_id))
    return [Ranked(item_id=i, matched_on=matched(i)) for i in ordered]


# ── What gets embedded ────────────────────────────────────────────────────────


def embedding_text(item: Item) -> str:
    """The text whose meaning a semantic search matches on.

    A composite of `raw` (the human context — "para el túnel al rds de qa: ssh …",
    which is what a meaning-query matches), the `title`, and the `tags`. `content` is
    a stripped subset of `raw`, so it is omitted, and a null content never changes the
    recipe.

    **Changing this recipe is a full reindex**: every stored vector was produced from
    this exact composition, so a different one makes every embedding stale.
    """
    parts: list[str] = [item.raw]
    if item.title:
        parts.append(item.title)
    if item.tags:
        parts.append(" ".join(item.tags))
    return "\n".join(parts)


# ── The one vector encoding, shared by the side table and the vec index ───────


def serialize_vector(vector: list[float]) -> bytes:
    """Pack a float vector into little-endian float32 bytes.

    The single encoding used both for the `item_embeddings.vector` blob and for what
    is fed to sqlite-vec, so the two never disagree. `float[N]` in vec0 is exactly
    this.
    """
    return struct.pack(f"<{len(vector)}f", *vector)


def deserialize_vector(blob: bytes) -> list[float]:
    """Unpack float32 bytes back into a vector. The inverse of `serialize_vector`."""
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]. Zero when either vector has no magnitude."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(dot / (norm_a * norm_b))


# ── The vector store seam ─────────────────────────────────────────────────────


class VectorStore(Protocol):
    """The seam over the vector index. Two methods, no more.

    `Vec0Store` is the sqlite-vec adapter used where the extension loads;
    `InMemoryVectorStore` is the pure-Python fallback used in tests and where it
    cannot load. `core.find` and `core.reindex` talk only to this protocol, so the
    ranking is identical regardless of which store backs it.
    """

    def upsert(self, item_id: int, vector: list[float]) -> None: ...

    def search(self, query: list[float], k: int) -> list[tuple[int, float]]: ...


class InMemoryVectorStore:
    """A pure-Python vector store: cosine similarity over vectors held in memory.

    The store used in every test and where sqlite-vec cannot load. No numpy — a
    personal drawer is small enough that a comprehension over a few hundred vectors is
    instant. Deterministic, so the fusion and relevance tests are reproducible.
    """

    def __init__(self) -> None:
        self._vectors: dict[int, list[float]] = {}

    def upsert(self, item_id: int, vector: list[float]) -> None:
        self._vectors[item_id] = vector

    def search(self, query: list[float], k: int) -> list[tuple[int, float]]:
        """The `k` nearest item ids to `query`, each with its cosine similarity, best
        first. Ties broken by id ascending, so the order is deterministic."""
        scored = [
            (item_id, _cosine(query, vector))
            for item_id, vector in self._vectors.items()
        ]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:k]


# ── Database-backed helpers (still interface-agnostic; they take a Session) ────


@dataclass(frozen=True)
class SearchResult:
    """One hit: the item as it renders, and how the search found it."""

    item: ItemView
    matched_on: MatchedOn


def fts_search(session: Session, query: str, limit: int) -> list[int]:
    """Item ids matching `query` in the FTS5 index, best first.

    FTS5's `rank` orders by relevance (BM25); a bare MATCH would order by rowid. A
    query that is not valid FTS5 syntax (a lone special character, an unbalanced
    quote) raises in SQLite — callers pass user text, so `core.find` catches that and
    treats it as no keyword hits, not an error. This is the raw SQL that FTS5
    genuinely requires; the exception to "no raw SQL in app code" is the virtual table
    itself (ADR-005).
    """
    rows = session.execute(
        text(
            "SELECT rowid FROM items_fts WHERE items_fts MATCH :q "
            "ORDER BY rank LIMIT :limit"
        ),
        {"q": query, "limit": limit},
    ).fetchall()
    return [row[0] for row in rows]


def load_vector_store(session: Session) -> InMemoryVectorStore:
    """Build an in-memory store from every stored embedding.

    The default vector backend where sqlite-vec cannot load: the vectors live in
    `item_embeddings` regardless, so search reads them straight into memory. Where the
    extension *does* load, `core.find` is handed a `Vec0Store` instead and this is not
    called.
    """
    store = InMemoryVectorStore()
    for row in session.scalars(select(ItemEmbedding)):
        store.upsert(row.item_id, deserialize_vector(row.vector))
    return store
