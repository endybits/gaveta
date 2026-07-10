"""Stage 0 smoke tests: the package imports, and the console script resolves."""

import re
from importlib.metadata import version

import pytest

import gaveta
from gaveta.cli import main

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
