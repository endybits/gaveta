"""Local classification — the contextual layer (Stage 4, ADR-004).

`gaveta.brain` turns post-gate text into a `Classification` (type / title / tags /
content). It is the *only* package permitted to import a network client (`httpx`), and
then only to reach a local Ollama — the architecture fence in
`tests/test_architecture.py` enforces both halves of that rule. Everything here runs
after the gate, so it only ever sees cleared or `[REDACTED]` text.

`make_classifier(config)` is the single seam the core and tests construct: it returns an
`OllamaClassifier` that degrades to `HeuristicClassifier` on any failure, so a caller
never has to know whether a model was reachable.
"""

from gaveta.brain.heuristic import HeuristicClassifier
from gaveta.brain.ollama import OllamaClassifier
from gaveta.brain.types import Classification, Classifier
from gaveta.config import ModelConfig, load_config

__all__ = [
    "Classification",
    "Classifier",
    "HeuristicClassifier",
    "OllamaClassifier",
    "make_classifier",
]


def make_classifier(config: ModelConfig | None = None) -> Classifier:
    """The default classifier: Ollama with a heuristic fallback.

    `config` defaults to `load_config()`, so a caller with no opinion gets the
    configured (or default) model. The returned classifier never blocks or fails — the
    contract the whole degrade-never-block design rests on.
    """
    return OllamaClassifier(config or load_config())
