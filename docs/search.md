# Search — how `gaveta f` ranks

`gaveta f "query"` finds items by meaning, not just keywords. This page explains how a
result list is built, and how it degrades honestly when a piece is missing. The decisions
behind it live in [ADR-005](adr/ADR-005-semantic-retrieval.md).

## Two rankers, fused

A search runs up to two rankings and combines them.

1. **Keyword (FTS5).** SQLite's full-text index over each item's `raw`, `title`, `content`,
   and `tags`, ranked by relevance (BM25). This is the **floor**: FTS5 is compiled into
   SQLite, so it works on every machine, always.

2. **Vector (sqlite-vec).** A semantic search over embeddings — vectors that place items
   with similar *meaning* near each other, so a query can match an item that shares no
   words with it. This runs only where the `sqlite-vec` extension loads (see *Degraded
   modes*).

The two ranked lists are merged by **Reciprocal Rank Fusion (RRF)**: each item scores
`1 / (k + rank)` for every list it appears in (`k = 60`), and results are ordered by the
summed score. The effect is that an item **both** rankers surface rises above one that only
one of them found — agreement wins. When the vector ranking is empty (no model, or no
extension), RRF reduces cleanly to the keyword order, so there is one ranking path, not two.

Each hit is tagged with how it was found — `keyword`, `semantic`, or `both` — which is what
`f --json` reports. It is deliberately *not* a numeric score: a raw fusion score would differ
between a keyword-only machine and a vector-capable one, and the wire contract must not depend
on that.

## What gets embedded

An item's embedding is computed from a composite of its **`raw` text, `title`, and `tags`**.
`raw` carries the human context a meaning-query matches on; `content` is a stripped subset of
`raw`, so it is left out. Changing this recipe means every stored embedding is stale — it is a
full `reindex`, not a config tweak.

## `reindex`

Embedding is **lazy**: capture stays fast and never calls the embedding model. Instead,
`gaveta reindex` embeds every item that lacks an embedding and reports `embedded N of M`. It
is idempotent (a rerun with nothing new reports `embedded 0 of M`), it heals items captured
while the model was down, and it re-embeds items whose text a `retag` changed.

A newly captured item is therefore **keyword-searchable immediately** and becomes
**semantically searchable after the next `reindex`**.

## Degraded modes (and how they are signalled)

Search has two optional dependencies, and every combination is usable:

| Ollama (embeddings) | sqlite-vec (vector index) | What `gaveta f` does |
|---|---|---|
| available | loads | Hybrid: keyword + vector, fused |
| available | cannot load | **Keyword-only**, with a stderr notice; embeddings still stored |
| absent | either | **Keyword-only**; nothing to embed, heals on a later `reindex` |

The "keyword search only — vector index unavailable" notice is printed to **stderr**, so
`f --json` and `f | …` stay clean on stdout. **`sqlite-vec` loads only where the Python
interpreter's `sqlite3` was built with loadable-extension support** — many Homebrew and pyenv
Pythons are not, so keyword-only is a common and fully-supported mode, not a failure. Because
embeddings are stored regardless, copying a drawer to a machine where the extension *does* load
lets `reindex` rebuild the vector index without re-contacting Ollama.

## Empty results

A search that matches nothing prints a "no matches" notice to stderr, an empty array under
`--json`, and **exits 0** — like `gaveta ls` on an empty drawer. Finding nothing is a
successful search, not the "you named a missing thing" error that `gaveta show <id>` returns
as exit 1.
