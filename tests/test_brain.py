"""The classifier: the heuristic floor, and the Ollama adapter that degrades to it.

No test here requires a running Ollama — CI has none. The adapter's one HTTP call is a
seam (`_post`) the tests replace with `monkeypatch.setattr`, the same convention the CLI
uses for `_prompt_choice`. Every failure mode is driven by making that seam raise or
return junk, and the assertion is always the same: a capture is never lost.
"""

import json
from typing import Any

import httpx
import pytest

from gaveta.brain import make_classifier
from gaveta.brain.heuristic import HeuristicClassifier
from gaveta.brain.ollama import OllamaClassifier
from gaveta.config import ModelConfig
from gaveta.db.models import ItemType

# ── HeuristicClassifier ───────────────────────────────────────────────────────────────

URL = "https://sqlite.org/withoutrowid.html"


def test_lone_url_is_a_link_with_the_url_as_content() -> None:
    result = HeuristicClassifier().classify(URL)
    assert result.type is ItemType.link
    assert result.content == URL
    assert result.title  # a readable label, not None


def test_url_among_prose_is_a_link_with_the_bare_url_as_content() -> None:
    text = f"{URL} leer antes de optimizar"
    result = HeuristicClassifier().classify(text)
    assert result.type is ItemType.link
    assert result.content == URL


@pytest.mark.parametrize(
    "text",
    [
        "git rebase -i main",
        "$ sudo systemctl restart nginx",
        "docker compose up -d",
        "ssh rds-qa.internal",
    ],
)
def test_shell_ish_text_is_a_command_with_content(text: str) -> None:
    result = HeuristicClassifier().classify(text)
    assert result.type is ItemType.command
    assert result.content is not None
    assert result.content.strip() == " ".join(text.split())


def test_prose_is_a_note_with_null_content() -> None:
    result = HeuristicClassifier().classify("una nota cualquiera sobre el almuerzo")
    assert result.type is ItemType.note
    assert result.content is None
    assert result.title == "una nota cualquiera sobre el almuerzo"


def test_empty_text_is_a_note_with_null_title() -> None:
    result = HeuristicClassifier().classify("   ")
    assert result.type is ItemType.note
    assert result.title is None
    assert result.content is None


# ── OllamaClassifier: the happy path (contract) ───────────────────────────────────────


def _ollama_body(inner: dict[str, Any]) -> dict[str, Any]:
    """Wrap a model object as Ollama's /api/generate does: JSON text in `response`."""
    return {"response": json.dumps(inner)}


def _config() -> ModelConfig:
    return ModelConfig()


def test_valid_json_becomes_the_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clf = OllamaClassifier(_config())
    monkeypatch.setattr(
        clf,
        "_post",
        lambda text: {
            "type": "command",
            "title": "restart qa replica",
            "tags": ["ssh", "rds", "qa"],
            "content": "ssh rds-qa && systemctl restart pg",
        },
    )
    result = clf.classify("some deploy note about the qa replica")
    assert result.type is ItemType.command
    assert result.title == "restart qa replica"
    assert result.tags == ["ssh", "rds", "qa"]
    assert result.content == "ssh rds-qa && systemctl restart pg"


def test_prompt_carries_the_input_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """The strict-JSON prompt must actually contain the text being classified."""
    captured: dict[str, str] = {}

    def fake_httpx_post(url: str, **kwargs: Any) -> httpx.Response:
        captured["prompt"] = kwargs["json"]["prompt"]
        captured["format"] = kwargs["json"]["format"]
        return httpx.Response(
            200, json=_ollama_body({"type": "note"}), request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(httpx, "post", fake_httpx_post)
    OllamaClassifier(_config()).classify("classify me please")
    assert "classify me please" in captured["prompt"]
    assert captured["format"] == "json"


# ── OllamaClassifier: every failure falls back to the heuristic ───────────────────────


def _raise(exc: Exception) -> Any:
    def _seam(text: str) -> Any:
        raise exc

    return _seam


def test_malformed_json_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    clf = OllamaClassifier(_config())

    def bad_post(text: str) -> dict[str, Any]:
        raise json.JSONDecodeError("no", "doc", 0)

    monkeypatch.setattr(clf, "_post", bad_post)
    result = clf.classify(URL)
    # fell through to the heuristic: a lone URL is a link with the URL as content
    assert result.type is ItemType.link
    assert result.content == URL


def test_timeout_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    clf = OllamaClassifier(_config())
    monkeypatch.setattr(clf, "_post", _raise(httpx.TimeoutException("slow")))
    assert clf.classify("git status").type is ItemType.command


def test_connection_refused_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    clf = OllamaClassifier(_config())
    monkeypatch.setattr(clf, "_post", _raise(httpx.ConnectError("refused")))
    assert clf.classify("just a note").type is ItemType.note


def test_non_200_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    clf = OllamaClassifier(_config())

    def fake_httpx_post(url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(500, text="boom", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_httpx_post)
    assert clf.classify(URL).type is ItemType.link  # heuristic


@pytest.mark.parametrize(
    "inner",
    [
        {"type": "credential_ref"},  # storage-only, not a live classification
        {"type": "unknown"},  # never a live verdict
        {"type": "banana"},  # not an ItemType at all
        {"title": "no type key"},  # missing type
        {"type": 3},  # wrong type for `type`
        {"type": "note", "tags": "not-a-list"},  # tags not a list
        {"type": "note", "tags": [1, 2]},  # tags not strings
        {"type": "note", "title": 5},  # title wrong type
        {"type": "link", "content": 7},  # content wrong type
    ],
)
def test_contract_violations_fall_back(
    monkeypatch: pytest.MonkeyPatch, inner: dict[str, Any]
) -> None:
    clf = OllamaClassifier(_config())
    monkeypatch.setattr(clf, "_post", lambda text: inner)
    # note-shaped input, so the heuristic yields a note — proof we did not trust `inner`
    result = clf.classify("una nota sobre el almuerzo")
    assert result.type is ItemType.note
    assert result.content is None


def test_empty_strings_normalize_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A model that returns empty title/content strings yields None, not ''."""
    clf = OllamaClassifier(_config())
    monkeypatch.setattr(
        clf,
        "_post",
        lambda text: {
            "type": "note",
            "title": "  ",
            "tags": ["", " x "],
            "content": "",
        },
    )
    result = clf.classify("whatever")
    assert result.title is None
    assert result.content is None
    assert result.tags == ["x"]


# ── the factory ───────────────────────────────────────────────────────────────────────


def test_make_classifier_returns_ollama_with_heuristic_fallback() -> None:
    clf = make_classifier(ModelConfig())
    assert isinstance(clf, OllamaClassifier)
    assert isinstance(clf._fallback, HeuristicClassifier)


def test_make_classifier_defaults_to_loaded_config(gaveta_home: Any) -> None:
    """With no config file, the factory still builds; load_config returns defaults."""
    clf = make_classifier()
    assert isinstance(clf, OllamaClassifier)
