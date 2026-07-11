"""Add the nullable `content` column.

The middle of the three layers (raw / content / title): the clean copyable payload the
Stage 4 classifier extracts. Nullable, because plain prose has no bare payload and the
heuristic floor leaves it null for anything but a lone URL. Existing rows survive the
upgrade with `content = NULL`; the downgrade drops the column cleanly.

Rendered as `sa.Text()`, its database primitive — a migration is frozen history and must
not import app column types (ADR-002). SQLite ALTER goes through batch mode, as
`render_as_batch=True` in env.py requires.

Revision ID: e0e5bf21467f
Revises: 83e1b56e69e6
Create Date: 2026-07-11 06:40:21.574737

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e0e5bf21467f"
down_revision: str | Sequence[str] | None = "83e1b56e69e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.add_column(sa.Column("content", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.drop_column("content")
