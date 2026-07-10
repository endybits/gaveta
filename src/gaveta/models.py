"""The wire models — the contracts every later stage honors.

Two of them, and the split is deliberate (ADR-002). `CaptureRequest` is what goes *in*;
`ItemView` is what comes *out* once a capture has been persisted and given an id. The
row that sits between them is `gaveta.db.models.Item`, and `gaveta.mapping` is the only
place that converts.

Both schemas are snapshot-tested, so a change to either shows up as an explicit diff in
review rather than as a surprise in a client. Keeping storage out of `CaptureRequest` is
what let Stage 2 add an output contract without touching the input one.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from gaveta.db.models import ItemType

# Widened in Stage 4, when classification lands. Until then a capture is only
# ever `unknown`, and the Literal makes that a type error to violate rather than
# a convention to remember.
CaptureType = Literal["unknown"]

# The interface is the CLI, whether the text arrived as an argument or over a
# pipe. `stdin` is a transport, not a source, so it is deliberately not a value
# here: inventing one would add contract the spec does not ask for.
CaptureSource = Literal["cli"]


class CaptureRequest(BaseModel):
    """What the user handed us. The input contract, frozen since Stage 1.

    Nothing about storage belongs here. `id`, `created_at` and `updated_at` are facts
    the database authors, not facts a caller may assert, and `source` is an input fact
    the row has no use for.
    """

    raw: str
    source: CaptureSource = "cli"
    captured_at: datetime
    type: CaptureType = "unknown"
    tags: list[str] = Field(default_factory=list)


class ItemView(BaseModel):
    """A capture that has been saved: the output contract.

    What `show`, `export`, and `--json` emit, and what Stage 7's HTTP routes return.
    It is a plain pydantic model rather than a live `Item`, so serializing it after its
    session has closed cannot raise `DetachedInstanceError`.

    `type` is the *storage* vocabulary (`ItemType`, all five members), not the wire
    vocabulary `CaptureType` — this model describes a row, and a row's type is whatever
    the database may hold. Importing the enum rather than restating its members is what
    stops the two from drifting apart in silence.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    raw: str
    type: ItemType
    title: str | None
    tags: list[str]
    # UTC, with an explicit +00:00 offset on the wire. A consumer wanting local time
    # converts; a consumer reading a naive string would have to guess. See ADR-002.
    created_at: datetime
    updated_at: datetime
