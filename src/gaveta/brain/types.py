"""What a classifier produces, and the shape every classifier honors.

`Classification` is *internal* — it never crosses the `--json` wire (only `ItemView`
does). It is a frozen dataclass, matching how the codebase already reaches for stdlib
dataclasses/enums for its internal values (`Verdict`, `ItemType`). The mapping layer
lifts its fields onto the stored row.

The three-layer story lives in these fields: `raw` (the immutable original) is held by
the caller; the classifier adds `title` (the readable label), `content` (the copyable
payload, nullable), and `type`/`tags`.
"""

from dataclasses import dataclass, field
from typing import Protocol

from gaveta.db.models import ItemType


@dataclass(frozen=True)
class Classification:
    """A capture, described. The output of any `Classifier`."""

    type: ItemType
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    content: str | None = None


class Classifier(Protocol):
    """The seam. `classify(text) -> Classification`, and nothing else.

    Pure and synchronous by contract: it takes post-gate text (cleared or `[REDACTED]`)
    and returns a description. It must never raise on bad input, never block forever,
    never lose a capture — a classifier that cannot answer returns a heuristic guess, it
    does not fail. That invariant is what lets `core.capture` call it unconditionally.
    """

    def classify(self, text: str) -> Classification: ...


class Embedder(Protocol):
    """The seam. `embed(text) -> vector | None`.

    Returns the embedding as a list of floats, or `None` when no model is reachable — an
    embedder that cannot answer says so rather than raising. There is no heuristic floor
    for embeddings (unlike classification): a missing vector is not a wrong guess, it is
    a gap that `reindex` heals the next time a model is up. `reindex` skips an item
    whose embedder returns `None`, so a drawer captured while Ollama was down becomes
    semantically searchable later, never blocking or crashing in the meantime.
    """

    def embed(self, text: str) -> list[float] | None: ...
