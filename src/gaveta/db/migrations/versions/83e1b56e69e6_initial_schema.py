"""initial schema

Revision ID: 83e1b56e69e6
Revises:
Create Date: 2026-07-10

The first migration, and the only path by which an `items` table is ever created:
`Base.metadata.create_all()` appears nowhere in `src/`.

Autogenerate drafted this file and got one thing wrong, which is why it is committed as
source rather than as output. It rendered the custom column types by qualified name —
`gaveta.db.types.JsonList()` — without emitting the import, so the module raised
`NameError` on first run.

The fix is not to add the import. A migration is frozen history: it must keep describing
the schema it created even after `gaveta.db.types` is refactored, renamed, or deleted.
So it names what those decorators *are* at the database level — `sa.Text` and
`sa.DateTime` — and the invariants they enforce live in the application, where they
belong. See docs/adr/ADR-002-persistence-and-time.md.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "83e1b56e69e6"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column(
            "type",
            # native_enum=False → VARCHAR + a named CHECK. The name is what lets a later
            # migration drop and recreate this constraint under SQLite's batch mode.
            sa.Enum(
                "link",
                "command",
                "note",
                "credential_ref",
                "unknown",
                name="item_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=True),
        # gaveta.db.types.JsonList at the application level; TEXT holding a JSON array
        # at the database level.
        sa.Column("tags_json", sa.Text(), nullable=False),
        # gaveta.db.types.UtcDateTime; UTC is enforced in Python, since SQLite's
        # DATETIME cannot hold an offset.
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_items")),
    )
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.create_index("ix_items_created_at", ["created_at"], unique=False)
        batch_op.create_index("ix_items_type", ["type"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.drop_index("ix_items_type")
        batch_op.drop_index("ix_items_created_at")

    op.drop_table("items")
