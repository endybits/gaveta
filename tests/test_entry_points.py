"""Every way to invoke Gaveta reaches the same `main`.

`python -m gaveta` is exercised through a real subprocess, because importing
`gaveta.__main__` *runs* the CLI — there is no way to cover it in-process without also
executing it.
"""

import os
import subprocess
import sys
from importlib.metadata import entry_points
from pathlib import Path

import pytest


def run_dash_m(*args: str, home: Path) -> subprocess.CompletedProcess[str]:
    """Invoke `python -m gaveta` in a fresh interpreter, against `home`."""
    return subprocess.run(
        [sys.executable, "-m", "gaveta", *args],
        capture_output=True,
        text=True,
        env={**os.environ, "GAVETA_HOME": str(home)},
        check=False,
    )


def test_python_dash_m_gaveta_is_a_working_entry_point(tmp_path: Path) -> None:
    """`sys.executable -m gaveta` is unambiguous where a console script on PATH is not.

    The cross-process persistence tests depend on this invocation form.
    """
    result = run_dash_m("--version", home=tmp_path / "drawer")

    assert result.returncode == 0
    assert "gaveta" in result.stdout


def test_dash_m_captures_from_an_argument(tmp_path: Path) -> None:
    result = run_dash_m("via dash-m", home=tmp_path / "drawer")

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("script", ["gaveta", "gv"])
def test_both_console_scripts_share_one_entry_point(script: str) -> None:
    """`gv` is an alias, not a fork. They cannot diverge; one test says so.

    Read from the installed distribution metadata rather than by shelling out, so this
    asserts what was *packaged* rather than whatever happens to be first on PATH.
    """
    scripts = {ep.name: ep.value for ep in entry_points(group="console_scripts")}

    assert scripts[script] == "gaveta.cli:main"
