"""Add the `item_embeddings` table — the portable source of truth for embeddings.

Stage 5 stores each item's embedding vector here, in an ordinary table present on every
machine, rather than only in the sqlite-vec index (`vec_items`). The index is a loadable
native extension many Python builds cannot load, so it is a rebuildable cache; this
table is what makes embeddings portable and lets `reindex` heal a `vec_items` from
stored blobs without re-embedding through Ollama. One row per item, cascade-deleted with
it. See docs/adr/ADR-005-semantic-retrieval.md.

Unlike the FTS5 migration, this is an ordinary relational table in `Base.metadata`, so
it is created with `op.*` ops and participates in the model/migration drift check
normally. Custom column types are rendered by their database primitive
(`sa.LargeBinary`), the frozen-history rule from the initial schema — a migration must
not import app types.

Revision ID: b2c3d4e5f6a7
Revises: a1f2c3d4e5f6
Create Date: 2026-07-12 09:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1f2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "item_embeddings",
        # PK and FK both: exactly one embedding per item, gone when the item is gone.
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        # gaveta stores the float32 vector as raw bytes; BLOB at the database level.
        sa.Column("vector", sa.LargeBinary(), nullable=False),
        # gaveta.db.types.UtcDateTime; UTC enforced in Python, as elsewhere.
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
            name=op.f("fk_item_embeddings_item_id_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("item_id", name=op.f("pk_item_embeddings")),
    )


def downgrade() -> None:
    op.drop_table("item_embeddings")
