"""Stage 0 smoke tests: the package imports, and the console scripts resolve."""

import re
from importlib.metadata import entry_points, version

import pytest

import gaveta
from gaveta.cli import main

# Both installed commands. `gv` is an alias sharing `gaveta`'s entry point.
CONSOLE_SCRIPTS = ("gaveta", "gv")

# A permissive PEP 440 release prefix: enough to catch an empty string or a
# placeholder, without pulling in `packaging` as a dependency at Stage 0.
_VERSION_RE = re.compile(r"^\d+\.\d+")


def test_version_is_exported() -> None:
    assert gaveta.__version__
    assert _VERSION_RE.match(gaveta.__version__), gaveta.__version__


def test_version_matches_distribution_metadata() -> None:
    """`pyproject.toml` is the single source of truth for the version.

    Fails if anyone reintroduces a hardcoded literal in `src/`, which would
    drift from the pyproject on the first `cz bump`.
    """
    assert gaveta.__version__ == version("gaveta-cli")


def test_cli_entry_point_runs(capsys: pytest.CaptureFixture[str]) -> None:
    """Prove the `[project.scripts]` target is real, not just declared.

    Stage 0's `main()` printed the version. Stage 1's captures text, so the
    version moved behind `--version`; the point of the test is unchanged.
    """
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert gaveta.__version__ in capsys.readouterr().out


def _console_script(name: str) -> object:
    """The callable a console script resolves to, per installed metadata."""
    scripts = {ep.name: ep for ep in entry_points(group="console_scripts")}
    assert name in scripts, f"console script {name!r} is not installed"
    return scripts[name].load()


@pytest.mark.parametrize("name", CONSOLE_SCRIPTS)
def test_console_script_is_installed_and_resolves(name: str) -> None:
    """Reads the installed distribution metadata, so a typo in
    `[project.scripts]` fails here rather than at a user's shell prompt."""
    assert _console_script(name) is main


def test_gv_is_an_alias_of_gaveta() -> None:
    """Same entry point, not a copy: one code path, so they cannot diverge."""
    assert _console_script("gv") is _console_script("gaveta")
