"""Reciprocal Rank Fusion, proven store-free.

`fuse` is a pure function over two id-lists — no database, no embedder, no vector
store. That is deliberate (ADR-005): the interesting ranking logic is testable in
isolation, and the vector path that CI cannot run (sqlite-vec will not load) never
gates these.
"""

from gaveta.search import MatchedOn, fuse


def _ids(ranked: list) -> list[int]:
    return [r.item_id for r in ranked]


def test_no_vectors_reduces_to_fts_order() -> None:
    """The degraded path: an empty vector ranking leaves FTS5 order untouched."""
    ranked = fuse([3, 1, 2], [])
    assert _ids(ranked) == [3, 1, 2]
    assert all(r.matched_on is MatchedOn.keyword for r in ranked)


def test_no_fts_reduces_to_vector_order() -> None:
    """Symmetric: a keyword query that matches nothing still surfaces vector hits."""
    ranked = fuse([], [5, 9])
    assert _ids(ranked) == [5, 9]
    assert all(r.matched_on is MatchedOn.semantic for r in ranked)


def test_an_item_in_both_lists_is_marked_both() -> None:
    ranked = fuse([1, 2], [2, 3])
    by_id = {r.item_id: r.matched_on for r in ranked}
    assert by_id[1] is MatchedOn.keyword
    assert by_id[2] is MatchedOn.both
    assert by_id[3] is MatchedOn.semantic


def test_agreement_between_lists_beats_a_single_list_top() -> None:
    """The point of fusion: an item both lists rank highly outranks either list's #1.

    Item 2 is second in each list; item 1 leads FTS5 and item 3 leads vectors. Because
    2 scores in *both*, its summed RRF score clears each singleton leader. This is the
    case that proves fusion does something a single ranker cannot.
    """
    ranked = fuse([1, 2], [3, 2])
    assert _ids(ranked)[0] == 2
    assert ranked[0].matched_on is MatchedOn.both


def test_fts_alone_ranks_wrong_and_vectors_fix_it() -> None:
    """FTS5 ranks the wanted item behind a lexical decoy; vectors rank it first, and
    fusion lifts it over the decoy — the "vectors fix a keyword ranking" case.

    Item 1 is a lexical decoy: it leads FTS5 (a keyword coincidence) but the vector
    search does not surface it at all. Item 7 is what the user meant: FTS5 ranks it
    second, but vectors rank it first. Fused, 7 (in both) beats 1 (keyword only), so
    meaning wins over the keyword coincidence — which FTS5 alone would not have done.
    """
    fts = [1, 7]  # decoy 1 leads on keywords, 7 second
    vec = [7]  # vectors surface only the meant item
    ranked = fuse(fts, vec)
    assert _ids(ranked)[0] == 7
    assert ranked[0].matched_on is MatchedOn.both
    # And FTS5 alone would have ranked the decoy first — proving fusion changed the
    # order.
    assert fts[0] == 1


def test_ties_break_by_id_for_determinism() -> None:
    """Two items with the same fused score come back in ascending-id order, always."""
    # Item 2 leads FTS5, item 1 leads vectors — both at rank 0, so identical scores.
    # The tiebreak must be id ascending, independent of insertion order.
    ranked = fuse([2], [1])
    assert _ids(ranked) == [1, 2]
