"""Reading `~/.gaveta/config.toml` — the model knobs, and nothing else yet.

The file is optional: absent means defaults, which is the common case (Ollama on the
standard port, the ADR-004 default model). Present-but-broken is a *usage* error — a
malformed TOML file or a non-localhost endpoint is a "your config is wrong" failure the
user fixes by editing the file, surfaced by the CLI at exit 2, not a new exit code and
not a crash.

Read-only via stdlib `tomllib`; Gaveta never writes this file. The endpoint is validated
as localhost here, in core, so the containment guarantee (ADR-004) does not lean on the
architecture test alone — a non-local endpoint is refused before any request is built.
"""

import re
import tomllib
from dataclasses import dataclass

from gaveta.paths import config_path

# The ADR-004 default. A small instruct model, good at strict JSON and bilingual input,
# that `ollama pull`s cleanly. Overridable in config; validation against real samples is
# the user's manual checklist.
DEFAULT_MODEL = "qwen2.5:3b-instruct"
DEFAULT_ENDPOINT = "http://localhost:11434"
DEFAULT_TIMEOUT = 2.5

# The ADR-005 default embedding model, and the dimension it produces. `nomic-embed-text`
# is a small retrieval-trained model that `ollama pull`s cleanly and handles bilingual
# input. The dimension is baked into the `vec_items` schema, so it is a constant, not a
# config knob: changing the embedding model is a full reindex, and a model whose vectors
# are not `EMBEDDING_DIM` wide is refused rather than allowed to corrupt the index.
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
EMBEDDING_DIM = 768

# The hosts a configured endpoint may name. Anything else is refused: the classifier
# only ever dials the local machine (ADR-004, layer-4 containment). Mirrors the
# architecture test's list, enforced here so the property holds at runtime, not just CI.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# Pull the host out of `scheme://host[:port]/…` without urllib — that module is on the
# network-import ban list (its parsing half is innocent, but the fence bans by name),
# and a scheme/host/port endpoint is regular enough for one anchored pattern. The host
# is either a bracketed IPv6 literal or a run of non-`:/` characters after the `//`.
_HOST_RE = re.compile(
    r"^[a-zA-Z][a-zA-Z0-9+.\-]*://(?:\[(?P<v6>[^\]]+)\]|(?P<host>[^:/?#]+))"
)


class ConfigError(Exception):
    """A present config file that is broken. The CLI maps this to exit 2 (usage)."""


@dataclass(frozen=True)
class ModelConfig:
    """The `[model]` block, resolved. A frozen value with validated defaults.

    One block serves both the classifier (`name`) and the embedder (`embedding_model`),
    which share an endpoint and a timeout. Constructed by keyword everywhere, so adding
    a field with a default breaks no caller.
    """

    name: str = DEFAULT_MODEL
    endpoint: str = DEFAULT_ENDPOINT
    timeout: float = DEFAULT_TIMEOUT
    embedding_model: str = DEFAULT_EMBEDDING_MODEL


def _require_localhost(endpoint: str) -> None:
    match = _HOST_RE.match(endpoint)
    host = (match.group("v6") or match.group("host")) if match else None
    if host not in _LOCAL_HOSTS:
        raise ConfigError(
            f"config endpoint must be localhost, got {endpoint!r}. "
            "Gaveta never talks to a non-local model (see ADR-004)."
        )


def load_config() -> ModelConfig:
    """The resolved model config. Missing file → defaults; broken file → `ConfigError`.

    Only keys Gaveta knows are read; anything else in the file is ignored, so a config
    can carry forward-looking keys without tripping this. A wrong *type* (a string
    timeout, say) is a usage error, not a silent coercion.
    """
    path = config_path()
    if not path.exists():
        return ModelConfig()

    try:
        raw = tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc

    model = raw.get("model", {})
    if not isinstance(model, dict):
        raise ConfigError(
            f"[model] in {path} must be a table, got {type(model).__name__}"
        )

    name = model.get("name", DEFAULT_MODEL)
    endpoint = model.get("endpoint", DEFAULT_ENDPOINT)
    timeout = model.get("timeout", DEFAULT_TIMEOUT)
    embedding_model = model.get("embedding_model", DEFAULT_EMBEDDING_MODEL)

    if not isinstance(name, str) or not name:
        raise ConfigError(f"[model].name in {path} must be a non-empty string")
    if not isinstance(endpoint, str) or not endpoint:
        raise ConfigError(f"[model].endpoint in {path} must be a non-empty string")
    if not isinstance(embedding_model, str) or not embedding_model:
        raise ConfigError(
            f"[model].embedding_model in {path} must be a non-empty string"
        )
    # bool is an int subclass; reject it so `timeout = true` is not silently read as 1.
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
    ):
        raise ConfigError(f"[model].timeout in {path} must be a positive number")

    _require_localhost(endpoint)
    return ModelConfig(
        name=name,
        endpoint=endpoint,
        timeout=float(timeout),
        embedding_model=embedding_model,
    )
