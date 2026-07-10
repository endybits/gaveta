"""Column types that enforce, rather than declare, the storage invariants.

`DateTime(timezone=True)` is a *no-op on SQLite*: the dialect writes the wall-clock
digits, discards the offset, and reads back a naive datetime. Declaring the intent is
therefore not enough — something has to enforce it, and that something is `UtcDateTime`.

See docs/adr/ADR-002-persistence-and-time.md.
"""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Dialect, Text, TypeDecorator
from sqlalchemy.types import DateTime


class UtcDateTime(TypeDecorator[datetime]):
    """Aware in, aware out; UTC in the column. Naive datetimes are rejected.

    A naive datetime is not "local time" — it is an instant the caller declined to
    specify, one of many possible. Coercing it by guessing is precisely the data loss
    this type exists to prevent, so the guess is refused: `ValueError`, not a default.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """Normalize to UTC on the way in."""
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "naive datetime refused: attach a timezone before persisting. "
                "A naive value has no instant, and guessing one silently corrupts "
                "the row the first time the clock or the timezone changes."
            )
        return value.astimezone(UTC)

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """Re-attach UTC on the way out; SQLite hands back a naive value."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class JsonList(TypeDecorator[list[str]]):
    """A list of strings, stored as a JSON array in a TEXT column.

    Not SQLite's JSON1 extension: this must work on any build, and Gaveta never queries
    *into* the tags from SQL. Stage 5's retrieval is semantic, not a `json_each` join.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: list[str] | None, dialect: Dialect) -> str:
        """`None` and `[]` are the same absence, and both store as `[]`."""
        return json.dumps(list(value or []))

    def process_result_value(self, value: str | None, dialect: Dialect) -> list[str]:
        if not value:
            return []
        parsed: Any = json.loads(value)
        return [str(tag) for tag in parsed]


__all__ = ["JsonList", "UtcDateTime"]
