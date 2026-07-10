# Data model

Gaveta stores captures in a local SQLite database. There is one table today, `items`.
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
| `id` | INTEGER PK | The id `ls`, `show`, and `rm` speak. |
| `raw` | TEXT NOT NULL | Exactly what you captured, unmodified. |
| `type` | VARCHAR + CHECK | One of the five below. `unknown` until Stage 4 classifies. |
| `title` | TEXT NULL | Nullable for now; Stage 4's classifier fills it. |
| `tags_json` | TEXT NOT NULL | A JSON array of strings. Surfaced in code as `tags`. |
| `created_at` | DATETIME NOT NULL | UTC. See "Time" below. |
| `updated_at` | DATETIME NOT NULL | UTC. |

Two indexes: `ix_items_created_at` (`ls` orders by it, newest first) and `ix_items_type`
(`ls <type>` filters on it).

### The `type` enum

```
link · command · note · credential_ref · unknown
```

Stored as `VARCHAR` plus a **named** CHECK constraint (`ck_items_item_type`) — SQLite has
no native enum, and the name is what lets a later migration widen the set under SQLite's
batch mode. All five members exist from day one at the storage level, even though a Stage 2
capture is only ever `unknown`: classification lands in Stage 4.

The wire model that a *caller* provides (`CaptureRequest`) is narrower — its `type` is
fixed at `unknown` — so a caller cannot assert a classification the system has not
performed. The two vocabularies are joined in one place, `gaveta.mapping`.

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
