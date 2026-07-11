"""The Ollama adapter — the contextual layer, when a model is available.

`OllamaClassifier` POSTs post-gate text to a local Ollama with a strict-JSON prompt and
parses `{type, title, tags, content}` back. It is an Adapter over `HeuristicClassifier`:
*any* failure — connection refused, timeout, non-200, invalid or partial JSON, an
out-of-vocabulary type — delegates to the wrapped heuristic. It never raises to the
caller and never loses a capture (ADR-004). `retag` re-runs it, so a fallback is an
upgrade waiting to happen, not a dead end.

This is the *only* module in the codebase permitted to import `httpx`, and only to reach
the localhost endpoint the config validated. Both halves of that are enforced by
`tests/test_architecture.py`.
"""

import json
from typing import Any

import httpx

from gaveta.brain.heuristic import HeuristicClassifier
from gaveta.brain.types import Classification
from gaveta.config import ModelConfig
from gaveta.db.models import ItemType

# The types the model may return. `credential_ref` and `unknown` are storage-only: the
# gate owns credentials, and a live classification is never "unknown". So the model's
# vocabulary is narrower than ItemType, and anything outside it falls back.
_ALLOWED_TYPES = {ItemType.link, ItemType.command, ItemType.note}

# The strict-JSON contract. Ollama's `format=json` constrains the decoder to valid JSON;
# the prompt constrains the *shape*. The rules and worked examples steer the two cases
# that matter most: a URL inside prose is still a `link` whose content is the bare URL,
# and a command wrapped in narrative keeps only the command line. Bilingual by design —
# captures mix English and Spanish.
_PROMPT = """\
You classify a captured note for a developer's personal drawer. Reply with a single \
JSON object and nothing else.

Schema:
  "type":    one of "link", "command", "note"
  "title":   a short human label (<= 80 chars), same language as the input
  "tags":    0-5 short lowercase tags, an array of strings
  "content": the clean copyable payload with the surrounding narrative stripped away

Rules:
- If the text contains a URL, type is "link" and content is the bare URL, even when \
the URL sits inside a sentence. Keep only the URL in content, not the prose around it.
- If the text is (or wraps) a shell command, type is "command" and content is the \
bare command line, without the explanation around it.
- Otherwise type is "note" and content is null — plain prose has no copyable payload.
- Answer in the same language as the input.

Examples:
Input: Documentacion de uv, importante para el proyecto https://docs.astral.sh/uv/
Output: {{"type": "link", "title": "Documentacion de uv", "tags": ["uv", "docs"], \
"content": "https://docs.astral.sh/uv/"}}
Input: para reiniciar la replica de qa: ssh rds-qa && systemctl restart pg
Output: {{"type": "command", "title": "reiniciar replica qa", "tags": ["ssh", "qa"], \
"content": "ssh rds-qa && systemctl restart pg"}}
Input: recordar comprar cafe antes del standup
Output: {{"type": "note", "title": "comprar cafe", "tags": [], "content": null}}

Input:
{text}
"""


class OllamaClassifier:
    """Classify via a local Ollama, falling back to heuristics on any failure."""

    def __init__(
        self, config: ModelConfig, *, fallback: HeuristicClassifier | None = None
    ) -> None:
        self._config = config
        self._fallback = fallback or HeuristicClassifier()

    def classify(self, text: str) -> Classification:
        try:
            payload = self._post(text)
            parsed = self._parse(payload)
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError, TypeError):
            return self._fallback.classify(text)
        if parsed is None:
            return self._fallback.classify(text)
        return parsed

    def _post(self, text: str) -> dict[str, Any]:
        """The one HTTP call. Isolated as a seam the tests fake without a real Ollama.

        A hard total timeout bounds how slow capture may feel; a slow model is a
        fallback, not an error. Raises on any transport failure, which `classify` turns
        into a heuristic result.
        """
        response = httpx.post(
            f"{self._config.endpoint}/api/generate",
            json={
                "model": self._config.name,
                "prompt": _PROMPT.format(text=text),
                "format": "json",
                "stream": False,
            },
            timeout=self._config.timeout,
        )
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        # Ollama wraps the model's text in a "response" field; the text is itself JSON.
        inner: dict[str, Any] = json.loads(body["response"])
        return inner

    def _parse(self, obj: dict[str, Any]) -> Classification | None:
        """Validate the model's object against the contract. `None` → fall back.

        Conservative: an unknown type, a non-string title, or non-string tags mean the
        model did not honor the contract, so we prefer the deterministic heuristic to a
        half-trusted result.
        """
        raw_type = obj.get("type")
        if not isinstance(raw_type, str):
            return None
        try:
            item_type = ItemType(raw_type)
        except ValueError:
            return None
        if item_type not in _ALLOWED_TYPES:
            return None

        title = obj.get("title")
        if title is not None and not isinstance(title, str):
            return None

        raw_tags = obj.get("tags", [])
        if not isinstance(raw_tags, list) or not all(
            isinstance(t, str) for t in raw_tags
        ):
            return None

        content = obj.get("content")
        if content is not None and not isinstance(content, str):
            return None

        return Classification(
            type=item_type,
            title=title.strip() if isinstance(title, str) and title.strip() else None,
            tags=[t.strip() for t in raw_tags if t.strip()],
            content=content if content else None,
        )
