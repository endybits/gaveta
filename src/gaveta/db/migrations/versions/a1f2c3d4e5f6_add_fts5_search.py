"""Add the FTS5 keyword-search index over `items`.

Stage 5's retrieval floor. `items_fts` is a standard FTS5 virtual table mirroring the
searchable text of each row — `raw`, `title`, `content`, and the tags — keyed by `rowid`
= `items.id`. It is the guaranteed base of `gaveta f`: FTS5 is a compile-time SQLite
module, so it works on every machine, unlike the sqlite-vec vector index, which needs a
loadable extension the author's Python cannot load. See
docs/adr/ADR-005-semantic-retrieval.md.

Two deliberate departures from the project's migration conventions, recorded here rather
than bent silently:

1. **Raw SQL.** A virtual table cannot be expressed with `op.*` ops, so this is the
   first migration to use `op.execute`. Frozen history is the right place for it — the
   app core stays free of raw SQL.

2. **Triggers, and a backfill.** `items_fts` is kept in sync by AFTER INSERT / UPDATE /
   DELETE triggers on `items`, so `core.py` keeps doing plain ORM writes and the keyword
   index stays consistent without application-level bookkeeping on every write. The
   triggers fire only on *future* writes, so the migration also **backfills the rows
   that already exist** — without it, a drawer captured before Stage 5 would return
   nothing from the first `gaveta f` after upgrade. FTS is searchable immediately after
   this migration; no `reindex` is needed (reindex backfills embeddings, not FTS).

The tags are stored as a JSON array in `items.tags_json`; the triggers index that
JSON text as-is. FTS5's default (unicode61) tokenizer splits on punctuation, so a
search for `rds` still matches a row tagged `["rds", "qa"]`.

Revision ID: a1f2c3d4e5f6
Revises: e0e5bf21467f
Create Date: 2026-07-12 09:15:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1f2c3d4e5f6"
down_revision: str | Sequence[str] | None = "e0e5bf21467f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A *standard* FTS5 table (no `content=`/`content_rowid=`): the text is duplicated
    # into the index. External-content would avoid the copy but requires the fragile
    # `'delete'` special-insert in every DELETE/UPDATE trigger to purge old tokens.
    # Captured text is short and a personal drawer is small, so the copy is negligible
    # and the triggers stay plain INSERT/DELETE by rowid — the correctness win the ADR
    # chose.
    #
    # `content` is an FTS column name here; in the trigger bodies `new.content` refers
    # to the SQLite `items.content` column that feeds it.
    op.execute("CREATE VIRTUAL TABLE items_fts USING fts5(raw, title, content, tags)")

    op.execute(
        "CREATE TRIGGER items_ai AFTER INSERT ON items BEGIN "
        "INSERT INTO items_fts(rowid, raw, title, content, tags) "
        "VALUES (new.id, new.raw, new.title, new.content, new.tags_json); "
        "END"
    )
    op.execute(
        "CREATE TRIGGER items_ad AFTER DELETE ON items BEGIN "
        "DELETE FROM items_fts WHERE rowid = old.id; "
        "END"
    )
    op.execute(
        "CREATE TRIGGER items_au AFTER UPDATE ON items BEGIN "
        "DELETE FROM items_fts WHERE rowid = old.id; "
        "INSERT INTO items_fts(rowid, raw, title, content, tags) "
        "VALUES (new.id, new.raw, new.title, new.content, new.tags_json); "
        "END"
    )

    # Backfill the rows that predate this migration. Triggers cover future writes only.
    op.execute(
        "INSERT INTO items_fts(rowid, raw, title, content, tags) "
        "SELECT id, raw, title, content, tags_json FROM items"
    )


def downgrade() -> None:
    # Drop the triggers first, then the table. Dropping the table takes its shadow
    # tables with it; the reverse backfill is moot.
    op.execute("DROP TRIGGER IF EXISTS items_au")
    op.execute("DROP TRIGGER IF EXISTS items_ad")
    op.execute("DROP TRIGGER IF EXISTS items_ai")
    op.execute("DROP TABLE IF EXISTS items_fts")
