"""The capture model — the contract every later stage honors.

Stage 1 only *simulates* saving, but the shape settled here is real: Stage 2
persists this model and Stage 4 widens `type`. Its JSON Schema is snapshot-tested,
so any change to these fields shows up as an explicit diff in review.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Widened in Stage 4, when classification lands. Until then a capture is only
# ever `unknown`, and the Literal makes that a type error to violate rather than
# a convention to remember.
CaptureType = Literal["unknown"]

# The interface is the CLI, whether the text arrived as an argument or over a
# pipe. `stdin` is a transport, not a source, so it is deliberately not a value
# here: inventing one would add contract the spec does not ask for.
CaptureSource = Literal["cli"]


class CaptureRequest(BaseModel):
    """What Gaveta *would* save. Stage 1 renders it; Stage 2 persists it."""

    raw: str
    source: CaptureSource = "cli"
    captured_at: datetime
    type: CaptureType = "unknown"
    tags: list[str] = Field(default_factory=list)
