"""The DoD line: save, restart the process, and `ls` still shows the item.

This is the one thing that cannot be faked in-process. Each command runs in a fresh
interpreter via `python -m gaveta`; the invocation form itself is covered in
test_entry_points.py, and here it is the vehicle for the persistence claims.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.conftest import seed_offline_config


def run_gaveta(*args: str, home: Path) -> subprocess.CompletedProcess[str]:
    """Invoke Gaveta in a brand-new interpreter, against `home`.

    Seeds an offline config so the subprocess never reaches a real Ollama and
    classification is the deterministic heuristic everywhere (`seed_offline_config`).
    """
    seed_offline_config(home)
    return subprocess.run(
        [sys.executable, "-m", "gaveta", *args],
        capture_output=True,
        text=True,
        env={**os.environ, "GAVETA_HOME": str(home)},
        check=False,
    )


def test_a_capture_survives_the_process_that_made_it(tmp_path: Path) -> None:
    """Two interpreters, one drawer. Nothing is shared but the file on disk."""
    home = tmp_path / "drawer"

    saved = run_gaveta("persist me", home=home)
    assert saved.returncode == 0, saved.stderr

    listed = run_gaveta("ls", home=home)

    assert listed.returncode == 0, listed.stderr
    assert "persist me" in listed.stdout


def test_the_database_file_is_created_on_a_fresh_machine(tmp_path: Path) -> None:
    """`~/.gaveta` does not exist until the first capture creates it."""
    home = tmp_path / "never-existed"
    assert not home.exists()

    result = run_gaveta("first ever capture", home=home)

    assert result.returncode == 0, result.stderr
    assert (home / "gaveta.db").is_file()


def test_two_homes_cannot_see_each_other(tmp_path: Path) -> None:
    """`GAVETA_HOME` is the whole isolation story, and it has to actually isolate."""
    first = tmp_path / "one"
    second = tmp_path / "two"

    run_gaveta("isolated", home=first)
    listed = run_gaveta("ls", home=second)

    assert listed.returncode == 0, listed.stderr
    assert "isolated" not in listed.stdout


def test_deleting_the_database_file_resets_the_world(tmp_path: Path) -> None:
    """The spec's own headline. It must not merely work — it must not crash after."""
    home = tmp_path / "drawer"
    run_gaveta("x", home=home)

    (home / "gaveta.db").unlink()
    listed = run_gaveta("ls", home=home)

    assert listed.returncode == 0, listed.stderr
    assert "x" not in listed.stdout


def test_export_reparses_and_the_count_matches(tmp_path: Path) -> None:
    """`export` round-trips: its output is valid JSON, and holds every capture."""
    home = tmp_path / "drawer"
    for raw in ("one", "two", "three"):
        run_gaveta(raw, home=home)

    exported = run_gaveta("export", home=home)

    assert exported.returncode == 0, exported.stderr
    parsed = json.loads(exported.stdout)
    assert [item["raw"] for item in parsed] == ["one", "two", "three"]
