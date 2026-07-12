# ADR-005 — Semantic retrieval: FTS5 is the floor, vectors are a cache, embeddings are portable schema

- **Status:** Accepted
- **Date:** 2026-07-12
- **Stage:** 5 — Semantic retrieval

## Context

Stage 5 makes the drawer *findable by meaning*. `gaveta f "query"` returns the top hits (id, type,
title); `-c` copies the best hit's paste-ready payload; `gaveta reindex` backfills embeddings. It is
the payoff of the three-layer model from Stage 4 (raw / content / title): retrieval's promise is
paste-ready output, so `-c` copies `content` when present and falls back to `raw`.

The design would be simple if it could assume a working vector index everywhere. It cannot, and that
single fact — probed, not assumed — reshapes the whole stage.

**`sqlite-vec` is a *loadable native SQLite extension*.** Loading it needs
`sqlite3.Connection.enable_load_extension`, which is a **compile-time** capability of the Python
interpreter, not something a program can turn on at runtime. On the primary development machine
(pyenv-built CPython 3.13.0) *and* the project's `uv` virtualenv, that method **does not exist** — the
interpreter was built without `--enable-loadable-sqlite-extensions` (confirmed via `sysconfig`
`CONFIG_ARGS`). Homebrew and pyenv Pythons commonly disable it; python.org framework builds and Debian/
Ubuntu system Python usually enable it; CI runners are a coin toss. So on the machine this project is
built on, **`sqlite-vec` cannot load at all.** SQLAlchemy 2.0 dropped its in-tree `apsw` dialect and
the third-party one is unmaintained, so swapping the DBAPI driver is not a clean escape.

**FTS5, by contrast, is a *compile-time* module** — no extension loading — and works everywhere
probed. That asymmetry is the design.

Four decisions follow, and each outlives the stage:

1. **What is the guaranteed retrieval floor, and what is best-effort?** If vectors can be absent on the
   author's own laptop and in CI, the product cannot depend on them for correctness.
2. **Where do embeddings live so they are not lost on a machine that cannot query them?** If embeddings
   live only in the vector index, the author's laptop stores none and vectors never work for them,
   ever.
3. **When does embedding run, and how does a stale embedding get healed?** Capture is the hot path; it
   already pays a classification budget. A retagged item's embedding goes stale and must be re-made.
4. **What happens when the configured embedding model returns the wrong dimension?** The dimension is
   baked into the vector schema; a mismatch must not corrupt the index.

Retrieval is *core*: `search(query, *, session)` and `reindex(*, session)` are pure seams that know
nothing of argv or a terminal, the same discipline `gate.scan` and `Classifier.classify` follow. The
embedder reaches Ollama through the same `brain/` fence as the classifier
([ADR-004](ADR-004-local-classification.md)); the containment narrative lives in
[`docs/security-model.md`](../security-model.md).

## Decision 1 — FTS5 keyword search is the floor; vector search is a best-effort enhancement fused on top

**Every `gaveta f` runs an FTS5 keyword search, which works on every machine. Where `sqlite-vec` loads,
a vector similarity search runs too, and the two ranked lists are combined by Reciprocal Rank Fusion
(RRF). Where it does not load — the author's laptop, and any CI runner without extension support —
retrieval is FTS5-only, signaled to the user, never a crash.**

The fusion is a store-free pure function, `fuse(fts_ranked, vec_ranked) -> ranked`, over two lists of
item ids. When vectors are unavailable, or when Ollama is down at search time and no query vector can
be computed, `vec_ranked` is simply `[]` and RRF reduces cleanly to FTS5 order. There is **one
retrieval path with a possibly-empty second input, not two branches** — which is both simpler to reason
about and cheaper to keep green under the coverage floor.

The FTS5-only notice is printed to **stderr**, not stdout, so `f --json` stays clean JSON on stdout and
`gaveta f "…" | …` is never polluted by a diagnostic. The notice is honest, not apologetic: keyword
search over a personal drawer is genuinely useful, and for a freshly captured item it is the *only*
thing that finds it until `reindex` runs (see Decision 3).

**Empty results are exit `0`, not an error.** `gaveta show 999` returns `NOT_FOUND` (exit 1) because the
user *named* a specific thing that is not there — an absence they asserted. `gaveta f "query"` that
matches nothing is a *successful search with an empty result set*, semantically like `gaveta ls` on an
empty drawer, which exits 0. A script piping `f` wants exit 0 plus an empty list (`[]` under `--json`),
not a failure it has to special-case; a friendly "no matches" goes to stderr.

## Decision 2 — Embeddings live in an ordinary `item_embeddings` table on every machine; the vector index is a rebuildable cache

**Each embedding is stored as a row in `item_embeddings(item_id, model, dim, vector, created_at)` — an
ordinary ORM-mapped table, created by a normal migration, present and writable on *every* machine
including the ones that cannot load `sqlite-vec`. The `vec_items` vector index is populated *from* that
table only where the extension loads. `vec_items` is a derived query cache, not the source of truth.**

This is the decision that dissolves the hard part. If embeddings lived only in `vec_items`, the author's
laptop — which cannot create `vec_items` at all — would compute embeddings into nothing, and copying that
drawer to a vector-capable machine would require re-embedding every item through Ollama from scratch.
With the side table, the laptop still *computes and stores* every embedding; a later `reindex` on a
vector-capable machine fills `vec_items` from the stored blobs with **no** Ollama round-trips. Embeddings
become portable across machines, and "reindex heals" holds even across the load/no-load boundary.

The consequence for the schema rule is a clean line: **the relational and FTS5 schema is single-path
(migrations); the vector index is cache (created lazily, never migrated).** `item_embeddings` and
`items_fts` are created by migrations that run *identically on every machine* — a migration never
contains DDL whose success depends on a runtime capability. `vec_items` is created with
`CREATE VIRTUAL TABLE IF NOT EXISTS … USING vec0(…)` at first reindex/search, guarded by the capability
probe. This keeps frozen migration history honest and keeps the machine-dependent piece out of it.

Two departures from convention are recorded here rather than bent silently. First, `items_fts` is
created with raw `op.execute("CREATE VIRTUAL TABLE …")` — the first raw-SQL migration in the project —
because a virtual table cannot be expressed with `op.*` ops. Second, that same migration installs
`INSERT`/`UPDATE`/`DELETE` **triggers** that keep `items_fts` in sync, and **backfills the rows that
already exist when it runs** (`INSERT INTO items_fts(rowid, …) SELECT id, … FROM items`). The triggers
put the sync in the *schema*, so `core.py` keeps doing plain ORM writes and **raw SQL never enters the
product core** — a stricter reading of "no raw SQL in app code" than threading FTS writes through
`capture`/`retag`/`delete`. The backfill matters on day one: triggers fire only on *future* writes, so
without it the author's existing ~28-item drawer would return nothing from the first `gaveta f` after
upgrade. FTS is therefore searchable immediately after the migration, with no `reindex` needed — `reindex`
backfills *embeddings*, not the keyword index.

`items_fts` (and its SQLite-managed shadow tables) and `vec_items` are excluded from the model/migration
drift check by a single shared predicate, so the check keeps guarding `items` and `item_embeddings`
normally without flagging the virtual tables it cannot describe.

## Decision 3 — Embedding is lazy (at reindex, not capture); a stale embedding is invalidated by the mutation that made it stale

**Capture stays classify-only: its latency is identical to Stage 4, and it never makes a second Ollama
call on the hot path. Embeddings are computed by `gaveta reindex`, which embeds every item that lacks an
`item_embeddings` row. A freshly captured item is FTS5-searchable the instant it is saved (via the
triggers) and becomes semantically searchable after the next reindex. When a writer changes an item's
embedded text — `retag` today, any future text-mutating writer — it deletes that item's `item_embeddings`
row in the same transaction, so reindex sees the item as missing and re-embeds it.**

**Why lazy, not embed-at-capture.** Two sequential Ollama calls on the capture path (classify, then
embed) would routinely blow the 2.5s classification budget and make capture feel slow — and capture is
the one path that must never regress, per [ADR-004](ADR-004-local-classification.md). Lazy embedding costs
capture *nothing*, leans on the "reindex heals" story already committed to, and loses only that a
brand-new item is keyword-searchable (not yet semantic) for the minutes until the next reindex — which is
exactly what FTS5-as-floor is for. It is also less code and removes the "embedder down at capture"
question entirely: capture never touches the embedder.

**Why invalidation travels with the mutation.** Reindex is defined as "embed the items lacking a row," so
the only thing needed to force a re-embed is to *remove the row*. Having `retag` delete the row in its own
transaction keeps "missing = needs embedding" as the single source of truth: reindex stays a plain loop
with no clock reasoning, no second pass comparing `embedding.created_at` against `item.updated_at`, no
timestamp-skew edge cases. The alternative — timestamp comparison — was rejected for exactly that added
machinery.

**Why the no-change edge is handled.** A heuristic `retag` that produces *identical* type/title/tags/
content is a no-op, and it must **not** invalidate the embedding, or `retag` stops being idempotent and
churns embeddings on every run. So `retag` deletes the embedding row **only when the embedded text
actually changed** — it compares the composite that gets embedded (`embedding_text`, below) before and
after. Changed text drops the row and the next reindex re-embeds it (count 1); unchanged text leaves the
row alone and the next reindex reports 0.

**What gets embedded** is a pure function `embedding_text(item)` composing **`raw` + `title` + `tags`**.
`raw` carries the human context — "para el túnel al rds de qa: ssh -L …" — which is the meaning a semantic
query matches on; `content` is a *stripped* subset of `raw` (the bare command), semantically thinner, so
it is omitted and a null `content` never changes the recipe. This choice defines what "meaning" means for
search, and **changing it is a full reindex** — stated so in the code and in [`docs/search.md`](../search.md).

## Decision 4 — A dimension mismatch is refused, never silently truncated

**The embedding dimension (`EMBEDDING_DIM = 768`, for the default `nomic-embed-text`) is baked into the
`vec_items` schema and the stored blobs. Config permits any `embedding_model`, and a different model may
return a different dimension. If the configured model returns a vector whose length is not
`EMBEDDING_DIM`, `reindex` refuses with a clear message and writes nothing — no truncation, no padding, no
automatic rebuild this stage.**

The message names the configured model, the returned dimension, the expected dimension, and the remedy:
change the model back, or delete `item_embeddings` and `vec_items` to rebuild the drawer under the new
model. A vector index silently fed vectors of the wrong dimension produces wrong distances with no error;
refusing loudly is the honest failure. Auto-rebuild-on-mismatch is deliberately out of scope for Stage 5 —
it is a destructive operation (it discards every stored embedding) and belongs behind an explicit command,
not a surprise inside `reindex`.

## The default embedding model, and the honesty of this record

Gaveta defaults to **`nomic-embed-text`** served by Ollama: a small (~274 MB) embedding model, first-class
in Ollama, trained for retrieval, and workable on bilingual (EN/ES) input, which the author's captures mix.
The dimension is 768. As with [ADR-004](ADR-004-local-classification.md), the config file makes the model a
one-line edit — but here the edit is heavier, because **changing the embedding model means a full reindex**
(a new model means new vectors, a possibly new dimension, and stored blobs that no longer match). That cost
is why the dimension is recorded and the mismatch is refused rather than papered over.

**On the honesty of this record.** The implementation environment has no Ollama and cannot load `sqlite-vec`
(both probed). So this decision states **what was assumed, not what was measured**: the model choice rests
on documented characteristics, not on retrieval quality measured against Gaveta's own drawer, and no
recall/latency numbers are quoted because none were produced here. The real validation is a **manual
checklist for the user's machine** — pull the model, reindex the ~28-item live drawer, run real meaning-
queries ("túnel rds", "pagos vencidos", "docs de uv") and judge the hits — and until it runs, the default
carries that caveat. Because this machine cannot load `sqlite-vec`, the *vector* path itself is exercised
only on a vector-capable machine and in the in-memory test store; the local manual session validates the
FTS5 floor, embedding storage, and the reindex heal.

## Consequences

**We accept** that on the primary development machine and possibly in CI, `gaveta f` is keyword-only. This
is not a degraded afterthought bolted on — it is the designed floor. Vector search is strictly additive,
lit up where the extension loads and fused on top, and its absence is signaled, never fatal. The zero-
friction and never-lose-a-capture principles outrank search quality, and this ordering encodes that.

**We accept** a second table (`item_embeddings`) and its storage cost (~3 KB per item at 768 float32) in
exchange for embeddings that survive on machines that cannot query them and travel to machines that can.
For a personal drawer the cost is negligible; the portability is the only thing that makes vectors ever
work for the author at all.

**We accept** the first raw-SQL migration and the first schema triggers, scoped to the FTS5 table and
justified in its docstring, so that `core.py` stays free of raw SQL and the keyword index stays consistent
without application-level bookkeeping on every write.

**We gain** a retrieval core that is pure and interface-agnostic: `search` and `reindex` know nothing of a
terminal, so the daemon (Stage 7), the web UI (Stage 8), and the MCP server (Stage 9) inherit them without
a rewrite — the same seam discipline as `gate.scan` and `classify`.

**We gain** a capture path whose latency is unchanged from Stage 4, because embedding never runs there.
The cost is that a brand-new item is keyword-searchable but not yet semantic until the next reindex — a
trade the FTS5 floor makes invisible for the common "find the thing I just saved" case.

**We give up**, deliberately, embed-at-capture and auto-rebuild-on-dimension-change. The first would
regress the hot path; the second would let `reindex` silently discard every embedding. Both are refused in
favor of an explicit, healable, non-destructive model.

## Revisiting this

Revisit the default embedding model the moment the manual validation says another model retrieves better on
the author's drawer — but budget the reindex, because unlike the classifier, changing this model is not
free. Revisit `EMBEDDING_DIM` only alongside the model, and never without deleting and rebuilding the vector
data.

Revisit the lazy-embedding decision only if "semantic search finds the thing I saved thirty seconds ago"
becomes a real need; even then, prefer a post-commit best-effort embed with its own budget over anything
that delays the `✓ saved` line. The capture-never-regresses invariant does not move.

Revisit the FTS5-only floor's *fusion weights* if the manual queries show keyword and vector hits fighting
rather than reinforcing — but not the floor itself. FTS5 stays the guaranteed base as long as a supported
Python can ship without loadable extensions, which is indefinitely.
