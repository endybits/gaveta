"""Path resolution, and the guarantee that tests never touch the real drawer.

`conftest.py` points `GAVETA_HOME` at a tmp directory for every test in the suite.
The guard tests below prove that fixture is doing its job — and, via a negative
control, that the guard itself is capable of failing. A guard that cannot fail is
not a guard; it is a comment.
"""

import os
from pathlib import Path

import pytest

from gaveta.paths import HOME_ENV_VAR, db_path, ensure_home, gaveta_home


def test_gaveta_home_honors_the_environment_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path))

    assert gaveta_home() == tmp_path


def test_gaveta_home_defaults_under_the_users_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(HOME_ENV_VAR, raising=False)

    assert gaveta_home() == Path.home() / ".gaveta"


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_override_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    """`Path("")` is the current directory. That is never what an empty var means."""
    monkeypatch.setenv(HOME_ENV_VAR, blank)

    assert gaveta_home() == Path.home() / ".gaveta"


def test_override_expands_a_tilde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HOME_ENV_VAR, "~/somewhere")

    assert gaveta_home() == Path.home() / "somewhere"


def test_db_path_sits_inside_the_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path))

    assert db_path() == tmp_path / "gaveta.db"
    assert db_path().parent == gaveta_home()


def test_resolving_a_path_creates_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Resolution is side-effect free; only `ensure_home` writes."""
    home = tmp_path / "not-yet"
    monkeypatch.setenv(HOME_ENV_VAR, str(home))

    gaveta_home()
    db_path()

    assert not home.exists()


def test_ensure_home_creates_the_directory_owner_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "drawer"
    monkeypatch.setenv(HOME_ENV_VAR, str(home))

    created = ensure_home()

    assert created.is_dir()
    # Stage 6 stores credential references here. Group- and world-readable bits on a
    # directory cannot be taken back later for directories already created.
    assert created.stat().st_mode & 0o077 == 0


def test_ensure_home_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(HOME_ENV_VAR, str(tmp_path / "drawer"))

    assert ensure_home() == ensure_home()


# --- The real-home guard, and proof that it can fire --------------------------


def test_the_suite_never_resolves_to_the_real_home() -> None:
    """The guard. No fixture, no monkeypatch: this reads the ambient environment.

    If `conftest.py`'s autouse fixture ever stops working, this test is what says so.
    """
    assert os.environ.get(HOME_ENV_VAR), (
        "conftest.py must set GAVETA_HOME for every test"
    )

    resolved = db_path()

    assert Path.home() not in resolved.parents, (
        f"the test suite resolved a database path inside the real home: {resolved}"
    )


def test_the_guard_would_fire_without_the_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control: unset the override and the guard's assertion must fail.

    Without this, `test_the_suite_never_resolves_to_the_real_home` could be passing
    vacuously — a guard that is structurally incapable of failing proves nothing.
    """
    monkeypatch.delenv(HOME_ENV_VAR, raising=False)

    resolved = db_path()

    assert Path.home() in resolved.parents
