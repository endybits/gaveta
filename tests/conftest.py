"""Suite-wide isolation: no test ever touches the real drawer.

`GAVETA_HOME` is redirected to a per-test tmp directory *autouse*, so isolation is
structural rather than something each test has to remember. The guard tests in
`test_paths.py` assert this fixture is doing its job, and a negative control there
proves the guard can actually fail.
"""

from pathlib import Path

import pytest

from gaveta.paths import HOME_ENV_VAR

# A localhost endpoint on a port nothing listens on. A subprocess is a real interpreter
# the in-process `no_real_model` fixture cannot reach, so a `gaveta` subprocess would
# call whatever Ollama is running on the developer's machine — nondeterministic, and
# against the no-real-model rule. Seeding a config pointing at a dead local port makes
# classification refuse instantly and fall back to the heuristic, on every machine,
# while still exercising the real capture → classify → persist path. Localhost, so the
# fence holds.
_DEAD_LOCAL_ENDPOINT = "http://127.0.0.1:1"


def seed_offline_config(home: Path) -> None:
    """Write a config that forces the heuristic path in a `gaveta` subprocess.

    Used by the cross-process tests, whose subprocesses no in-process patch can reach.
    """
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.toml").write_text(
        f'[model]\nendpoint = "{_DEAD_LOCAL_ENDPOINT}"\ntimeout = 0.5\n'
    )


@pytest.fixture(autouse=True)
def gaveta_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point `GAVETA_HOME` at a fresh directory for every test, without exception.

    Autouse and unconditional. A test that wants the default resolution back must
    `monkeypatch.delenv` it explicitly, which makes reading the real home a visible
    act rather than an oversight.
    """
    home = tmp_path / "gaveta-home"
    monkeypatch.setenv(HOME_ENV_VAR, str(home))
    return home


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test ever talks to a real Ollama — the model is mocked, always (CLAUDE.md).

    `make_classifier()` is the seam the CLI and core reach for; here it is redirected to
    the deterministic `HeuristicClassifier`, so a capture in any test classifies without
    a network call. A test that wants the Ollama adapter constructs it explicitly and
    fakes its `_post` seam; a test that wants a specific classification passes one in.
    Autouse, so a forgotten injection degrades to heuristics rather than hanging on a
    connection to a machine that may (the developer's) or may not (CI) run Ollama.
    """
    from gaveta.brain.heuristic import HeuristicClassifier

    heuristic = HeuristicClassifier()
    # Patch every module that reaches for the factory. Miss one and a test hits a real
    # Ollama on the developer's machine — nondeterministic, and against the rule.
    for module in ("gaveta.core", "gaveta.cli", "gaveta.subcommands"):
        monkeypatch.setattr(f"{module}.make_classifier", lambda *a, **k: heuristic)
