# Data model

Gaveta stores captures in a local SQLite database. The `items` table is the drawer; two
more objects support search (`item_embeddings` and the `items_fts` / `vec_items` indexes).
Everything here is created and evolved by Alembic migrations — see
[ADR-002](adr/ADR-002-persistence-and-time.md) for why, and for the two decisions that
shape this model most.

## Where it lives

```
$GAVETA_HOME/gaveta.db      # GAVETA_HOME overrides everything
~/.gaveta/gaveta.db         # the default
```

`GAVETA_HOME` wins if set; otherwise the drawer is `~/.gaveta`. The directory is created
owner-only (`0700`) on first use — it will hold credential *references* from Stage 6, and
a permissive mode cannot be taken back later.

**Deleting the database file resets the world.** The next command re-creates it, empty,
by running the migrations from scratch. There is no other state; the file is the drawer.

## The `items` table

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | The id `ls`, `show`, `retag`, and `rm` speak. |
| `raw` | TEXT NOT NULL | Exactly what you captured, unmodified. |
| `type` | VARCHAR + CHECK | One of the five below. The classifier sets it (Stage 4). |
| `title` | TEXT NULL | The readable label the classifier proposes. |
| `content` | TEXT NULL | The clean copyable payload (see the three layers below). |
| `tags_json` | TEXT NOT NULL | A JSON array of strings. Surfaced in code as `tags`. |
| `created_at` | DATETIME NOT NULL | UTC. See "Time" below. |
| `updated_at` | DATETIME NOT NULL | UTC. `retag` moves it; capture sets it equal to `created_at`. |

Two indexes: `ix_items_created_at` (`ls` orders by it, newest first) and `ix_items_type`
(`ls <type>` filters on it).

### The three layers: raw, content, title

A capture is stored in three layers, and each answers a different question:

- **`raw`** — *everything you captured*, immutable. The connection string with the note
  around it, the command with its explanation, the URL amid a sentence. It is never
  rewritten (except by `--redact`, at capture time, before it is ever stored).
- **`content`** — *the clean copyable part*, narrative stripped: the bare command, the
  bare URL, the bare snippet. Nullable, because plain prose has no copyable payload. The
  local model extracts it; the heuristic fallback fills it only for the trivially
  extractable case (a lone URL), and leaves it null otherwise.
- **`title`** — *the readable label*, a short human-facing name.

`raw` is what you said; `content` is what you'll copy; `title` is what you'll skim.
`retag <id>` re-derives `content`, `title`, `type`, and `tags` from `raw`.

### The `type` enum

```
link · command · note · credential_ref · unknown
```

Stored as `VARCHAR` plus a **named** CHECK constraint (`ck_items_item_type`) — SQLite has
no native enum, and the name is what let Stage 4's migration widen the set under SQLite's
batch mode. All five members exist at the storage level.

The wire model that a *caller* provides (`CaptureRequest`) is narrower: its `type` is one
of `link`, `command`, `note`, `unknown` — the values the classifier emits. `credential_ref`
is storage-only, the vault's business (Stage 6), never a live classification. `unknown` is
the degraded label a capture would carry only if classification produced nothing usable;
in practice even the heuristic floor never leaves a capture `unknown`. The two vocabularies
are joined in one place, `gaveta.mapping`.

## Search: `item_embeddings`, and the FTS5 / vector indexes

Stage 5's `gaveta f` ranks by meaning. Three objects support it; see
[docs/search.md](search.md) for how they rank and [ADR-005](adr/ADR-005-semantic-retrieval.md)
for the decisions.

**`item_embeddings`** — the portable source of truth for embeddings, one row per item:

| Column | Type | Notes |
|---|---|---|
| `item_id` | INTEGER PK, FK → `items.id` | One embedding per item, cascade-deleted with it. |
| `model` | TEXT NOT NULL | The embedding model that produced the vector. |
| `dim` | INTEGER NOT NULL | Its dimension — a mismatch is refused at `reindex`, not stored. |
| `vector` | BLOB NOT NULL | The float32 vector, the one encoding shared with the index. |
| `created_at` | DATETIME NOT NULL | UTC. |

This is an ordinary table, present on **every** machine, written by `reindex`. It exists so
embeddings survive on a machine that cannot query them and can be rebuilt into the vector
index on one that can — without re-contacting Ollama.

**`items_fts`** — a standard FTS5 virtual table indexing each item's `raw`, `title`,
`content`, and `tags`, kept in sync by triggers on `items` (the first migration to use raw
SQL, and the only place raw SQL lives in the schema). It is the keyword-search floor and
works on every machine.

**`vec_items`** — the `sqlite-vec` vector index. Unlike the tables above it is **not created
by a migration**: it is a rebuildable cache created lazily, and only where the `sqlite-vec`
extension can load (which depends on how the Python interpreter's `sqlite3` was built).
Migrations contain only DDL that runs identically everywhere, so this machine-dependent
object stays out of the chain. All three are excluded from the model/migration drift check
by a shared prefix predicate.

## Time

Every timestamp is stored in **UTC** and rendered in your **local** timezone.

This is not a preference. SQLAlchemy's `DateTime(timezone=True)` is a no-op on SQLite: it
discards the offset and reads back a naive datetime. Storing "local + offset" is therefore
not possible — what you would actually get is a naive local timestamp that becomes wrong
the moment you change timezone or DST rolls over, and unrecoverably so.

So the invariant, enforced by a column type (`UtcDateTime`) and asserted in tests:

- **Into the database**: every datetime is timezone-aware and normalized to UTC. A *naive*
  datetime is refused with a `ValueError`, never guessed at.
- **Out of the database**: every datetime is timezone-aware and UTC.
- **On screen** (`ls`, `show`): converted to your local timezone, to the second.
- **On the wire** (`--json`, `export`): UTC with an explicit `Z` suffix. A consumer that
  wants local time converts; one reading a naive string would have to guess.

## Migrations

The migration scripts live *inside the package* at `src/gaveta/db/migrations/`, so the
installed wheel ships them and an installed Gaveta can create its own database. The schema
is created by Alembic and only by Alembic — `create_all()` is called nowhere in the source,
so the migration chain a developer writes is exactly the one a user runs.

```bash
# Against a throwaway drawer, never your real one:
GAVETA_HOME=$(mktemp -d) uv run alembic upgrade head
GAVETA_HOME=$(mktemp -d) uv run alembic revision --autogenerate -m "describe the change"
```

`alembic.ini` at the repo root is a developer convenience; its database URL is empty by
design, supplied at runtime from `GAVETA_HOME`, so no command can migrate a drawer you did
not name.

## Backup

```bash
gaveta export > backup.json
```

`export` writes a JSON array of every item to stdout, oldest first. Redirection is the file
story — there is no `--output` flag, because `>` already is one.
