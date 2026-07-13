"""Config loading: defaults when absent, a clear error when broken.

The GAVETA_HOME isolation fixture (conftest) already redirects `config_path()` into a
per-test directory, so writing `config.toml` here never touches the real drawer — the
same isolation that covers the database covers the config file.
"""

from pathlib import Path

import pytest

from gaveta.config import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_ENDPOINT,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    ConfigError,
    load_config,
)
from gaveta.paths import config_path


def _write_config(home: Path, body: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    config_path().write_text(body)


def test_config_path_lives_under_gaveta_home(gaveta_home: Path) -> None:
    assert config_path() == gaveta_home / "config.toml"


def test_missing_file_yields_defaults(gaveta_home: Path) -> None:
    assert not config_path().exists()
    cfg = load_config()
    assert cfg.name == DEFAULT_MODEL
    assert cfg.endpoint == DEFAULT_ENDPOINT
    assert cfg.timeout == DEFAULT_TIMEOUT
    assert cfg.embedding_model == DEFAULT_EMBEDDING_MODEL


def test_embedding_model_overrides_the_default(gaveta_home: Path) -> None:
    _write_config(gaveta_home, '[model]\nembedding_model = "mxbai-embed-large"\n')
    cfg = load_config()
    assert cfg.embedding_model == "mxbai-embed-large"
    # The classifier model is untouched — one block, two independent knobs.
    assert cfg.name == DEFAULT_MODEL


def test_empty_embedding_model_is_a_config_error(gaveta_home: Path) -> None:
    _write_config(gaveta_home, '[model]\nembedding_model = ""\n')
    with pytest.raises(ConfigError):
        load_config()


def test_present_file_overrides_defaults(gaveta_home: Path) -> None:
    _write_config(
        gaveta_home,
        '[model]\nname = "gemma2:2b"\n'
        'endpoint = "http://127.0.0.1:11434"\ntimeout = 1.5\n',
    )
    cfg = load_config()
    assert cfg.name == "gemma2:2b"
    assert cfg.endpoint == "http://127.0.0.1:11434"
    assert cfg.timeout == 1.5


def test_partial_file_fills_the_rest_from_defaults(gaveta_home: Path) -> None:
    _write_config(gaveta_home, '[model]\nname = "llama3.2:3b"\n')
    cfg = load_config()
    assert cfg.name == "llama3.2:3b"
    assert cfg.endpoint == DEFAULT_ENDPOINT
    assert cfg.timeout == DEFAULT_TIMEOUT


def test_unknown_keys_are_ignored(gaveta_home: Path) -> None:
    """A forward-looking key does not trip loading — Gaveta reads only what it knows."""
    _write_config(gaveta_home, '[model]\nname = "x"\nfuture_knob = 3\n')
    assert load_config().name == "x"


def test_malformed_toml_raises_config_error(gaveta_home: Path) -> None:
    _write_config(gaveta_home, "[model\nname = ")
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert str(config_path()) in str(exc.value)


def test_non_localhost_endpoint_is_refused(gaveta_home: Path) -> None:
    _write_config(gaveta_home, '[model]\nendpoint = "http://evil.example.com:11434"\n')
    with pytest.raises(ConfigError) as exc:
        load_config()
    assert "localhost" in str(exc.value)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://[::1]:11434",
    ],
)
def test_local_endpoints_pass(gaveta_home: Path, endpoint: str) -> None:
    _write_config(gaveta_home, f'[model]\nendpoint = "{endpoint}"\n')
    assert load_config().endpoint == endpoint


@pytest.mark.parametrize(
    "body",
    [
        '[model]\ntimeout = "soon"\n',  # wrong type
        "[model]\ntimeout = 0\n",  # non-positive
        "[model]\ntimeout = true\n",  # bool is not a number here
        '[model]\nname = ""\n',  # empty name
        "model = 3\n",  # [model] is not a table
    ],
)
def test_bad_values_raise_config_error(gaveta_home: Path, body: str) -> None:
    _write_config(gaveta_home, body)
    with pytest.raises(ConfigError):
        load_config()
