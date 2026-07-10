"""The gate's CLI behavior: the full tty/non-tty × verdict × --redact matrix.

Driven through `main(argv)` in-process. `sys.stdin` is a fake whose tty-ness we control,
and the `[v/r/s]` prompt is monkeypatched, so every cell of the matrix runs without a
real terminal. The raw-bytes redaction check reads the files under `GAVETA_HOME`
directly — the strongest assertion available that a secret never reached disk.
"""

import io
from pathlib import Path

import pytest

from gaveta import cli
from gaveta.cli import main
from gaveta.exit_codes import ExitCode

# A canonical, public AWS docs example — never a live key. See tests/fixtures.
AWS = "AKIAIOSFODNN7EXAMPLE"
BLOCKED_INPUT = f"deploy key: {AWS}"
# A real-shaped password with no detectable format: caught only by the context word.
SUSPICIOUS_INPUT = "password: MargaritaVerde2024!"
CLEAN_INPUT = "totally normal note about lunch"


class _FakeStdin(io.StringIO):
    """stdin whose tty-ness we control (mirrors test_cli.py's fake)."""

    def __init__(self, text: str = "", isatty: bool = False) -> None:
        super().__init__(text)
        self._isatty = isatty

    def isatty(self) -> bool:
        return self._isatty


@pytest.fixture
def tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", _FakeStdin(isatty=True))


def _pipe(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr("sys.stdin", _FakeStdin(text, isatty=False))


def _answer(monkeypatch: pytest.MonkeyPatch, choice: str) -> None:
    """Make the suspicious prompt return `choice` without a real terminal."""
    monkeypatch.setattr(cli, "_prompt_choice", lambda: choice)


def _row_count(home: Path) -> int:
    from gaveta import core
    from gaveta.db.session import session as db_session

    with db_session() as session:
        return len(core.list_items(session=session))


# ── blocked (known format) ────────────────────────────────────────────────────────────


def test_blocked_on_a_tty_exits_three_and_writes_nothing(
    tty: None, gaveta_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([BLOCKED_INPUT]) == ExitCode.BLOCKED
    err = capsys.readouterr().err
    assert "blocked" in err
    assert "AWS access key" in err
    assert _row_count(gaveta_home) == 0


def test_blocked_over_a_pipe_exits_three_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    gaveta_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _pipe(monkeypatch, f"clave: {AWS}\n")

    assert main(["-"]) == ExitCode.BLOCKED
    assert "AWS access key" in capsys.readouterr().err
    assert _row_count(gaveta_home) == 0


def test_blocked_never_prompts(
    tty: None, monkeypatch: pytest.MonkeyPatch, gaveta_home: Path
) -> None:
    """A known-format secret is not a judgment call — the prompt must not be reached."""

    def explode() -> str:
        raise AssertionError("blocked input must never reach the prompt")

    monkeypatch.setattr(cli, "_prompt_choice", explode)
    assert main([BLOCKED_INPUT]) == ExitCode.BLOCKED


# ── suspicious (high entropy / context word) ──────────────────────────────────────────


def test_suspicious_on_a_tty_save_anyway(
    tty: None,
    monkeypatch: pytest.MonkeyPatch,
    gaveta_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _answer(monkeypatch, "s")

    assert main([SUSPICIOUS_INPUT, "--json"]) == ExitCode.OK
    from gaveta.models import ItemView

    saved = ItemView.model_validate_json(capsys.readouterr().out)
    assert saved.raw == SUSPICIOUS_INPUT  # saved raw, verbatim


def test_suspicious_on_a_tty_redact(
    tty: None,
    monkeypatch: pytest.MonkeyPatch,
    gaveta_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _answer(monkeypatch, "r")

    assert main([SUSPICIOUS_INPUT, "--json"]) == ExitCode.OK
    from gaveta.models import ItemView

    saved = ItemView.model_validate_json(capsys.readouterr().out)
    assert "MargaritaVerde2024!" not in saved.raw
    assert "[REDACTED]" in saved.raw


@pytest.mark.parametrize("answer", ["v", "", "x", "no"])
def test_suspicious_on_a_tty_refuse_exits_three(
    tty: None,
    monkeypatch: pytest.MonkeyPatch,
    gaveta_home: Path,
    answer: str,
) -> None:
    """v, empty, or anything unrecognized refuses. Saving is opt-in, never default."""
    _answer(monkeypatch, answer)

    assert main([SUSPICIOUS_INPUT]) == ExitCode.BLOCKED
    assert _row_count(gaveta_home) == 0


def test_suspicious_over_a_pipe_blocks_and_names_the_escape_hatches(
    monkeypatch: pytest.MonkeyPatch,
    gaveta_home: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The critical cell: no tty to prompt, so refuse — never save, never hang."""
    _pipe(monkeypatch, f"{SUSPICIOUS_INPUT}\n")

    assert main(["-"]) == ExitCode.BLOCKED
    err = capsys.readouterr().err
    assert "--redact" in err
    assert "terminal" in err
    assert _row_count(gaveta_home) == 0


# ── clean ─────────────────────────────────────────────────────────────────────────────


def test_clean_on_a_tty_saves_without_a_prompt(
    tty: None, monkeypatch: pytest.MonkeyPatch, gaveta_home: Path
) -> None:
    def explode() -> str:
        raise AssertionError("clean input must never prompt")

    monkeypatch.setattr(cli, "_prompt_choice", explode)
    assert main([CLEAN_INPUT]) == ExitCode.OK
    assert _row_count(gaveta_home) == 1


def test_clean_over_a_pipe_saves(
    monkeypatch: pytest.MonkeyPatch, gaveta_home: Path
) -> None:
    _pipe(monkeypatch, f"{CLEAN_INPUT}\n")
    assert main(["-"]) == ExitCode.OK
    assert _row_count(gaveta_home) == 1


# ── --redact short-circuits every branch ──────────────────────────────────────────────


def test_redact_flag_blocked_arg_saves_masked(
    tty: None, gaveta_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--redact", BLOCKED_INPUT]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "✓ saved" in out
    assert "redacted" in out


def test_redact_flag_blocked_pipe_saves_masked(
    monkeypatch: pytest.MonkeyPatch, gaveta_home: Path
) -> None:
    """blocked × non-tty × --redact → redact + save (the escape hatch, exit 0)."""
    _pipe(monkeypatch, f"clave: {AWS}\n")
    assert main(["--redact", "-"]) == ExitCode.OK
    assert _row_count(gaveta_home) == 1


def test_redact_flag_suspicious_pipe_saves_masked(
    monkeypatch: pytest.MonkeyPatch, gaveta_home: Path
) -> None:
    """suspicious × non-tty × --redact → redact + save; the prompt is pre-empted."""

    def explode() -> str:
        raise AssertionError("--redact must not reach the prompt")

    monkeypatch.setattr(cli, "_prompt_choice", explode)
    _pipe(monkeypatch, f"{SUSPICIOUS_INPUT}\n")
    assert main(["--redact", "-"]) == ExitCode.OK
    assert _row_count(gaveta_home) == 1


def test_redact_of_clean_input_shows_no_redacted_marker(
    tty: None, gaveta_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--redact on a clean note masks nothing, and does not claim it did."""
    assert main(["--redact", CLEAN_INPUT]) == ExitCode.OK
    assert "redacted" not in capsys.readouterr().out


# ── --redact round-trip: the secret reaches no file under GAVETA_HOME ────────────


def test_redacted_secret_is_absent_from_every_file_under_home(
    tty: None, gaveta_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The strongest assertion: scan the raw bytes of every file, not just the ORM view.

    A secret could hide in the SQLite `-wal` write-ahead log or a `-journal` rollback
    file that a single-file `gaveta.db` check would miss, so this globs the whole home.
    """
    assert main(["--redact", BLOCKED_INPUT]) == ExitCode.OK

    needle = AWS.encode()
    files = [p for p in gaveta_home.rglob("*") if p.is_file()]
    assert files, "expected at least gaveta.db to exist"
    for path in files:
        assert needle not in path.read_bytes(), f"secret leaked into {path.name}"


# ── exit codes stay distinct ──────────────────────────────────────────────────────────


def test_blocked_exit_code_is_three_and_distinct_from_usage() -> None:
    assert ExitCode.BLOCKED == 3
    assert ExitCode.BLOCKED != ExitCode.USAGE


def test_empty_input_still_exits_two_not_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The codes did not collapse: empty input is USAGE, a secret is BLOCKED."""
    _pipe(monkeypatch, "")
    assert main([]) == ExitCode.USAGE


# The schema snapshots (CaptureRequest, ItemView) are enforced unchanged by
# test_models.py::test_schema_matches_snapshot. This stage touches neither model, so
# those snapshots cannot drift — no duplicate assertion is needed here.
