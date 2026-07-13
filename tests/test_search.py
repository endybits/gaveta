"""Retrieval end to end: find, reindex, and the degraded matrix.

Every test uses a deterministic fake embedder — no network, no Ollama, no sqlite-vec
(CI cannot load the extension). The fake maps text to an `EMBEDDING_DIM`-wide vector
over a tiny concept vocabulary, so semantically-related texts get similar vectors and
the relevance and fusion assertions are reproducible. The real `Vec0Store` is
exercised separately (test_vec0), where it can load.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from gaveta import core
from gaveta.config import EMBEDDING_DIM
from gaveta.db.models import ItemEmbedding
from gaveta.db.session import session as db_session
from gaveta.search import MatchedOn

# ── A deterministic fake embedder ─────────────────────────────────────────────

# A handful of concepts; each becomes one axis of the vector. A text's vector is the
# count of each concept's cue words, so texts about the same thing point the same way
# and cosine similarity is meaningful — enough to rank a meaning-adjacent query
# without keyword overlap. The rest of the EMBEDDING_DIM axes stay zero.
_CONCEPTS: dict[int, tuple[str, ...]] = {
    0: ("tunnel", "túnel", "ssh", "rds", "database", "qa", "postgres"),
    1: ("deploy", "deployment", "release", "ship", "rollout"),
    2: ("coffee", "café", "lunch", "standup", "meeting"),
    3: ("uv", "python", "package", "docs", "documentation"),
    4: ("payment", "pago", "invoice", "overdue", "vencido", "billing"),
}


class FakeEmbedder:
    """A deterministic embedder: a concept-count vector, `EMBEDDING_DIM` wide.

    Not a real embedding, but it has the one property the tests need — related texts
    get similar vectors — while being fully reproducible and offline.
    """

    def __init__(self, *, dim: int = EMBEDDING_DIM) -> None:
        self._dim = dim

    def embed(self, text: str) -> list[float] | None:
        lowered = text.lower()
        vector = [0.0] * self._dim
        for axis, cues in _CONCEPTS.items():
            vector[axis] = float(sum(lowered.count(cue) for cue in cues))
        return vector


class DownEmbedder:
    """An embedder with no model reachable — returns None for everything."""

    def embed(self, text: str) -> list[float] | None:
        return None


class WrongWidthEmbedder:
    """An embedder whose model returns a vector of the wrong dimension."""

    def embed(self, text: str) -> list[float] | None:
        return [0.1] * (EMBEDDING_DIM + 256)


@pytest.fixture
def session() -> Iterator[Session]:
    with db_session() as active:
        yield active


def _seed(session: Session, texts: list[str]) -> None:
    """Capture each text (heuristic classification, the CI path)."""
    for text in texts:
        core.capture(text, session=session)


# ── find: the FTS5 floor works with no embeddings at all ──────────────────────


def test_find_by_keyword_with_no_embeddings(session: Session) -> None:
    """The acceptance-criteria path: capture, then `find` hits via FTS5 alone.

    No reindex has run, so there are no vectors — retrieval is FTS5-only, and the ssh
    item is still the top hit for "tunel". Every hit is `keyword`.
    """
    _seed(
        session,
        [
            "para el tunel al rds de qa: ssh -L 5432:rds-qa:5432 jump",
            "notas del standup sobre el deploy de mañana",
        ],
    )

    results = core.find("tunel", session=session, embedder=DownEmbedder())

    assert results, "expected at least one hit"
    assert "tunel" in results[0].item.raw
    assert results[0].matched_on is MatchedOn.keyword


def test_find_returns_empty_for_no_match(session: Session) -> None:
    """A search that matches nothing is an empty list, not an error (exit 0 later)."""
    _seed(session, ["a note about coffee"])

    assert core.find("zzz-no-match", session=session, embedder=DownEmbedder()) == []


def test_a_malformed_fts_query_finds_nothing_rather_than_raising(
    session: Session,
) -> None:
    """User text need not be valid FTS5 syntax; a lone `*` finds nothing, no crash."""
    _seed(session, ["something findable"])

    # A bare `*` is a syntax error in FTS5; find must swallow it and return no keyword
    # hits.
    assert core.find("*", session=session, embedder=DownEmbedder()) == []


# ── find: semantic relevance and fusion ───────────────────────────────────────


def test_semantic_query_ranks_the_meaning_adjacent_item_top_three(
    session: Session,
) -> None:
    """The relevance smoke: a meaning-adjacent query (no shared keyword) ranks the right
    item in the top three.

    SLOT FOR REAL PAIRS: replace/extend these with the user's 3-5 real query->expected
    pairs from the ADR-004 validation session on the live drawer. Seeded meanwhile
    with reasonable pairs.
    """
    _seed(
        session,
        [
            "ssh -L 5432:rds-qa:5432 jump  # tunnel to the qa database",  # id 1
            "recordar comprar café antes del standup",  # id 2
            "manual deploy: ship the release to prod",  # id 3
        ],
    )
    embedder = FakeEmbedder()
    core.reindex(session=session, embedder=embedder)

    # "postgres qa" shares no word with item 1's text, but is concept-adjacent (axis
    # 0).
    results = core.find("postgres qa", session=session, embedder=embedder)

    top_three_ids = [r.item.id for r in results[:3]]
    assert 1 in top_three_ids


def test_fusion_marks_a_hit_found_by_both_paths(session: Session) -> None:
    """When keyword and vector both surface an item, it is marked `both` and leads."""
    _seed(
        session,
        [
            # id 1: matches "tunnel" by keyword AND by concept (axis 0)
            "ssh tunnel to the qa rds database",
            "a totally unrelated coffee note",  # id 2
        ],
    )
    embedder = FakeEmbedder()
    core.reindex(session=session, embedder=embedder)

    results = core.find("tunnel", session=session, embedder=embedder)

    assert results[0].item.id == 1
    assert results[0].matched_on is MatchedOn.both


# ── reindex: idempotence, healing, dimension refusal ──────────────────────────


def test_reindex_reports_counts_and_is_idempotent(session: Session) -> None:
    _seed(session, ["one", "two", "three"])
    embedder = FakeEmbedder()

    embedded, total = core.reindex(session=session, embedder=embedder)
    assert (embedded, total) == (3, 3)

    # A second run embeds nothing new — every item already has a row.
    embedded_again, total_again = core.reindex(session=session, embedder=embedder)
    assert (embedded_again, total_again) == (0, 3)


def test_reindex_heals_items_captured_while_ollama_was_down(session: Session) -> None:
    """Capture with no model leaves no embedding; a later reindex gives it one."""
    _seed(session, ["captured while the model was down"])

    # First reindex with a down embedder: nothing embedded, item still healable.
    embedded, total = core.reindex(session=session, embedder=DownEmbedder())
    assert (embedded, total) == (0, 1)
    assert session.get(ItemEmbedding, 1) is None

    # Model comes back: reindex now embeds the item.
    embedded, total = core.reindex(session=session, embedder=FakeEmbedder())
    assert (embedded, total) == (1, 1)
    assert session.get(ItemEmbedding, 1) is not None


def test_reindex_refuses_a_wrong_dimension_and_writes_nothing(
    session: Session,
) -> None:
    """A model returning the wrong-width vector is refused, not truncated (ADR-005)."""
    _seed(session, ["needs embedding"])

    with pytest.raises(core.DimensionMismatch) as exc:
        core.reindex(session=session, embedder=WrongWidthEmbedder())

    assert exc.value.expected == EMBEDDING_DIM
    assert exc.value.got == EMBEDDING_DIM + 256
    # Nothing was stored — the refusal is total.
    assert session.get(ItemEmbedding, 1) is None


# ── retag invalidation, both arms ─────────────────────────────────────────────


def test_retag_that_changes_text_reembeds_on_next_reindex(session: Session) -> None:
    """Changed embedded text drops the row; the next reindex re-embeds it (count 1)."""
    _seed(session, ["ssh tunnel to qa"])
    embedder = FakeEmbedder()
    core.reindex(session=session, embedder=embedder)
    assert session.get(ItemEmbedding, 1) is not None

    # A retag that assigns a different title/tags changes embedding_text →
    # invalidates.
    class Retagger:
        def classify(self, text: str):
            from gaveta.brain.types import Classification
            from gaveta.db.models import ItemType

            return Classification(
                type=ItemType.command,
                title="a brand new title",
                tags=["fresh", "tags"],
                content=None,
            )

    core.retag(1, session=session, classifier=Retagger())
    assert session.get(ItemEmbedding, 1) is None  # invalidated

    embedded, _ = core.reindex(session=session, embedder=embedder)
    assert embedded == 1  # re-embedded
    assert session.get(ItemEmbedding, 1) is not None


def test_retag_with_no_text_change_leaves_the_embedding(session: Session) -> None:
    """A no-op retag (identical title/tags) must not invalidate — reindex reports 0."""
    _seed(session, ["prose that a heuristic retag will not change"])
    embedder = FakeEmbedder()
    core.reindex(session=session, embedder=embedder)
    assert session.get(ItemEmbedding, 1) is not None

    # The default heuristic retag reproduces the same title/tags → no invalidation.
    core.retag(1, session=session)
    assert session.get(ItemEmbedding, 1) is not None  # untouched

    embedded, _ = core.reindex(session=session, embedder=embedder)
    assert embedded == 0  # nothing to re-embed
