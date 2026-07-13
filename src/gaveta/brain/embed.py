"""The Ollama embedding adapter — vectors for semantic retrieval (Stage 5, ADR-005).

`OllamaEmbedder` POSTs text to a local Ollama's `/api/embed` and parses the vector back.
Unlike the classifier it has no heuristic floor: there is no deterministic way to
approximate an embedding, so a failure — connection refused, timeout, non-200, a
malformed or wrong-shaped response — returns `None`. `reindex` skips a `None` and heals
the item on a later run when a model is up; capture never touches the embedder at all
(embedding is lazy, ADR-005 Decision 3), so nothing on the hot path depends on this.

Like `OllamaClassifier`, this lives under `brain/` — the only package allowed to import
`httpx`, and only to reach the localhost endpoint the config validated. Both halves are
enforced by `tests/test_architecture.py`.
"""

from typing import Any

import httpx

from gaveta.config import ModelConfig


class OllamaEmbedder:
    """Embed via a local Ollama, returning `None` on any failure."""

    def __init__(self, config: ModelConfig) -> None:
        self._config = config

    def embed(self, text: str) -> list[float] | None:
        try:
            payload = self._embed(text)
            return self._parse(payload)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return None

    def _embed(self, text: str) -> dict[str, Any]:
        """The one HTTP call. Isolated as a seam the tests fake without a real Ollama.

        Uses `/api/embed` (the batch endpoint, `{"embeddings": [[...]]}`), bounded by
        the same timeout as classification — a slow model is a skip, not an error. It
        raises on any transport failure, which `embed` turns into `None`.
        """
        response = httpx.post(
            f"{self._config.endpoint}/api/embed",
            json={"model": self._config.embedding_model, "input": text},
            timeout=self._config.timeout,
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        return body

    def _parse(self, obj: dict[str, Any]) -> list[float] | None:
        """Validate the response shape. `None` → the caller treats it as no vector.

        `/api/embed` returns `{"embeddings": [[float, ...]]}` — a list of vectors, one
        per input. We send one input, so we want the first vector. Anything else (an
        empty list, a non-numeric element, a missing key) is a contract violation, and a
        wrong-shaped vector silently stored would produce wrong distances with no error,
        so this is deliberately strict.
        """
        embeddings = obj.get("embeddings")
        if not isinstance(embeddings, list) or not embeddings:
            return None
        vector = embeddings[0]
        if not isinstance(vector, list) or not vector:
            return None
        # bool is an int subclass; a vector of booleans is not a real embedding.
        if not all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in vector
        ):
            return None
        return [float(x) for x in vector]
