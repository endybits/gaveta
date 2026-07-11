"""The `Item` row — what a capture becomes once it is on disk.

This is the *storage* model. The wire model (`gaveta.models.CaptureRequest`) and the
output model (`gaveta.models.ItemView`) are deliberately separate, joined by
`gaveta.mapping`. See docs/adr/ADR-002-persistence-and-time.md for why.
"""

import enum
from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Index, MetaData, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from gaveta.db.types import JsonList, UtcDateTime

# Alembic compares the live metadata against the migration chain. Without a naming
# convention, autogenerate emits unnamed constraints and indexes, and SQLite's batch
# mode cannot later drop what it cannot name. This is not cosmetic: it is what keeps
# Stage 4's widening of `type` a migration someone can actually write.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class ItemType(enum.StrEnum):
    """The storage vocabulary — all five members, from day one.

    Wider than the wire model's `CaptureType`, which stays `Literal["unknown"]` until
    classification lands in Stage 4. The two are genuinely different sets today, and
    `gaveta.mapping` is the one place that states how the first becomes the second.
    """

    link = "link"
    command = "command"
    note = "note"
    credential_ref = "credential_ref"
    unknown = "unknown"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Item(Base):
    """One captured thing. Deleting the database file resets the world."""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    raw: Mapped[str] = mapped_column(Text, nullable=False)

    # native_enum=False → VARCHAR. SQLite has no native enum type.
    #
    # create_constraint=True is load-bearing and NOT the default: without it SQLAlchemy
    # 2.0 emits a bare VARCHAR and nothing at the database level constrains `type`, so
    # a hand-written INSERT or a future migration bug could store anything. The DDL is
    # asserted in tests/test_db_types.py rather than trusted.
    #
    # The constraint is named via NAMING_CONVENTION above (`ck_items_item_type`),
    # because SQLite's batch mode cannot drop an unnamed constraint — that is what
    # makes Stage 4's widening of this column a migration someone can actually write.
    type: Mapped[ItemType] = mapped_column(
        SAEnum(
            ItemType,
            native_enum=False,
            create_constraint=True,
            name="item_type",
            validate_strings=True,
        ),
        nullable=False,
        default=ItemType.unknown,
    )

    # Nullable "for now": Stage 4's classifier fills it. A capture has no title until
    # something reads the text and proposes one.
    title: Mapped[str | None] = mapped_column(String(200), nullable=True, default=None)

    # The middle of the three layers (raw / content / title): the clean copyable payload
    # — the bare command, the bare URL, the bare snippet — with surrounding narrative
    # stripped. Nullable by design: plain prose has no bare payload to extract, and the
    # heuristic floor leaves it null for anything but a lone URL. Text, not String(n):
    # a snippet has no natural length bound the way a title does.
    content: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    # The column is `tags_json` (it holds a JSON array); the attribute is `tags`,
    # because callers think in tags, not in storage encodings.
    tags: Mapped[list[str]] = mapped_column(
        "tags_json", JsonList, nullable=False, default=list
    )

    # UTC, always, enforced by the column type rather than by convention. Assigned in
    # Python, never by server_default=func.now(): SQLite's CURRENT_TIMESTAMP produces a
    # naive UTC string that bypasses UtcDateTime entirely.
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)

    __table_args__ = (
        # `ls` orders by this, newest first.
        Index("ix_items_created_at", "created_at"),
        # `ls <type>` filters on this.
        Index("ix_items_type", "type"),
    )

    def __repr__(self) -> str:
        return f"Item(id={self.id!r}, type={self.type!r}, raw={self.raw[:32]!r})"
