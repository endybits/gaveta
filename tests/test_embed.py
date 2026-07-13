"""The embedder: the Ollama adapter that returns a vector, or `None` on any failure.

No test here needs a running Ollama — CI has none. The one HTTP call is a seam
(`_embed`) the tests replace with `monkeypatch.setattr`, the same convention as the
classifier. Every failure mode is driven by making the seam raise or return junk, and
the assertion is the same: a failure is `None`, never an exception, so `reindex` skips.
"""

from typing import Any

import httpx
import pytest

from gaveta.brain import make_embedder
from gaveta.brain.embed import OllamaEmbedder
from gaveta.config import ModelConfig


def _config() -> ModelConfig:
    return ModelConfig()


def _embed_body(vector: list[float]) -> dict[str, Any]:
    """Wrap a vector as /api/embed does: a list of vectors under `embeddings`."""
    return {"embeddings": [vector]}


# ── The happy path (contract) ─────────────────────────────────────────────────


def test_valid_response_becomes_a_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    emb = OllamaEmbedder(_config())
    monkeypatch.setattr(emb, "_embed", lambda text: _embed_body([0.1, 0.2, 0.3]))

    assert emb.embed("túnel al rds de qa") == [0.1, 0.2, 0.3]


def test_integer_elements_are_coerced_to_float(monkeypatch: pytest.MonkeyPatch) -> None:
    emb = OllamaEmbedder(_config())
    monkeypatch.setattr(emb, "_embed", lambda text: _embed_body([0, 1, 0]))

    result = emb.embed("anything")
    assert result == [0.0, 1.0, 0.0]
    assert all(isinstance(x, float) for x in result)


def test_the_request_carries_the_input_and_embedding_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wire request must send the text as `input` and the configured embed model."""
    captured: dict[str, Any] = {}

    def fake_httpx_post(url: str, **kwargs: Any) -> httpx.Response:
        captured["url"] = url
        captured["json"] = kwargs["json"]
        return httpx.Response(
            200,
            json=_embed_body([1.0, 2.0]),
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_httpx_post)
    OllamaEmbedder(_config()).embed("embed me please")

    assert captured["url"].endswith("/api/embed")
    assert captured["json"]["input"] == "embed me please"
    assert captured["json"]["model"] == ModelConfig().embedding_model


# ── Every failure mode returns None, never raises ─────────────────────────────


def test_connection_refused_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(text: str) -> dict[str, Any]:
        raise httpx.ConnectError("refused")

    emb = OllamaEmbedder(_config())
    monkeypatch.setattr(emb, "_embed", refuse)
    assert emb.embed("x") is None


def test_timeout_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(text: str) -> dict[str, Any]:
        raise httpx.ReadTimeout("slow")

    emb = OllamaEmbedder(_config())
    monkeypatch.setattr(emb, "_embed", timeout)
    assert emb.embed("x") is None


def test_non_200_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def bad_status(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(500, text="boom", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", bad_status)
    assert OllamaEmbedder(_config()).embed("x") is None


@pytest.mark.parametrize(
    "body",
    [
        {},  # no `embeddings` key
        {"embeddings": []},  # empty list of vectors
        {"embeddings": [[]]},  # an empty vector
        {"embeddings": [["a", "b"]]},  # non-numeric elements
        {"embeddings": [[True, False]]},  # bool is not a real embedding value
        {"embeddings": "not a list"},  # wrong type entirely
    ],
)
def test_malformed_shapes_return_none(
    monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]
) -> None:
    emb = OllamaEmbedder(_config())
    monkeypatch.setattr(emb, "_embed", lambda text: body)
    assert emb.embed("x") is None


# ── The factory ───────────────────────────────────────────────────────────────


def test_make_embedder_returns_an_ollama_embedder() -> None:
    assert isinstance(make_embedder(_config()), OllamaEmbedder)


def test_make_embedder_defaults_to_loaded_config() -> None:
    """A caller with no opinion gets the configured (or default) model, not a crash."""
    assert isinstance(make_embedder(), OllamaEmbedder)
