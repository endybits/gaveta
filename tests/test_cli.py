"""The resolution table: every input class has exactly one outcome.

`main(argv)` takes its arguments by injection, so these run in-process with no
`subprocess` and no real terminal. stdin is faked via monkeypatch, which lets the
tty and non-tty branches both be exercised deterministically — the distinction
that decides how `gaveta` behaves on a CI runner.
"""

import io
import json
from typing import TextIO

import pytest

from gaveta.cli import main
from gaveta.commands import SUBCOMMANDS
from gaveta.models import CaptureRequest


class _FakeStdin(io.StringIO):
    """A stdin whose tty-ness we control, and that records whether it was read."""

    def __init__(self, text: str = "", isatty: bool = False) -> None:
        super().__init__(text)
        self._isatty = isatty
        self.was_read = False

    def isatty(self) -> bool:
        return self._isatty

    def read(self, *args: int | None) -> str:
        self.was_read = True
        return super().read()


@pytest.fixture
def tty_stdin(monkeypatch: pytest.MonkeyPatch) -> _FakeStdin:
    """No piped input: a terminal with a human at it."""
    fake = _FakeStdin(isatty=True)
    monkeypatch.setattr("sys.stdin", fake)
    return fake


def _pipe(monkeypatch: pytest.MonkeyPatch, text: str) -> _FakeStdin:
    fake = _FakeStdin(text, isatty=False)
    monkeypatch.setattr("sys.stdin", fake)
    return fake


# --- Row 3: argument form ----------------------------------------------------


def test_argument_form_captures_and_exits_zero(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["test note"]) == 0

    out = capsys.readouterr().out
    assert "[gaveta] would save:" in out
    assert "test note" in out


def test_argument_form_shows_all_five_fields(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["test note"])

    out = capsys.readouterr().out
    for label in ("raw", "type", "tags", "captured", "source"):
        assert f"  {label:<8} : " in out, f"missing field: {label}"


def test_argument_form_joins_multiple_tokens(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["hello", "world"]) == 0
    assert "hello world" in capsys.readouterr().out


def test_argument_form_never_reads_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lazy-stdin contract: reading it here hangs on an open pipe."""
    fake = _pipe(monkeypatch, "should not be read")

    assert main(["from argument"]) == 0
    assert fake.was_read is False


# --- Row 2: explicit stdin ---------------------------------------------------


def test_dash_reads_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _pipe(monkeypatch, "piped note\n")

    assert main(["-"]) == 0
    assert "piped note" in capsys.readouterr().out


def test_dash_and_argument_forms_produce_the_same_structure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`echo "..." | gaveta -` behaves identically to the argument form."""
    _pipe(monkeypatch, "same text\n")
    main(["-", "--json"])
    piped = json.loads(capsys.readouterr().out)

    monkeypatch.setattr("sys.stdin", _FakeStdin(isatty=True))
    main(["same text", "--json"])
    argument = json.loads(capsys.readouterr().out)

    assert piped.keys() == argument.keys()
    assert piped["raw"] == argument["raw"] == "same text"
    assert piped["source"] == argument["source"] == "cli"


def test_dash_with_empty_stdin_is_nothing_to_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pipe(monkeypatch, "")

    assert main(["-"]) == 2


# --- Row 4: bare pipe with content -------------------------------------------


def test_bare_pipe_captures_without_the_dash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _pipe(monkeypatch, "implicit\n")

    assert main([]) == 0
    assert "implicit" in capsys.readouterr().out


# --- Rows 5 & 6: empty input, on a pipe and on a tty --------------------------


@pytest.mark.parametrize(
    "stdin_text",
    ["", "   \n", "\n\n", "\t  \t"],
    ids=["empty", "spaces", "newlines", "tabs"],
)
def test_empty_or_blank_pipe_exits_two(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stdin_text: str,
) -> None:
    """Row 5. CI runners have non-tty stdin, so this is the path CI takes."""
    _pipe(monkeypatch, stdin_text)

    assert main([]) == 2

    err = capsys.readouterr().err
    assert "usage: gaveta" in err
    assert "nothing to capture" in err


def test_no_input_on_a_tty_exits_two(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    """Row 6. Same outcome as row 5: tty and non-tty behave identically."""
    assert main([]) == 2

    err = capsys.readouterr().err
    assert "usage: gaveta" in err
    assert "nothing to capture" in err


def test_usage_goes_to_stderr_not_stdout(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    main([])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""


def test_whitespace_only_argument_is_nothing_to_capture(
    tty_stdin: _FakeStdin,
) -> None:
    assert main(["   "]) == 2


# --- Row 1: reserved first token ---------------------------------------------


@pytest.mark.parametrize("name", sorted(SUBCOMMANDS))
def test_reserved_word_alone_exits_two(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    assert main([name]) == 2

    err = capsys.readouterr().err
    assert f"'{name}' is a reserved command" in err
    assert f"Stage {SUBCOMMANDS[name]}" in err


@pytest.mark.parametrize("name", sorted(SUBCOMMANDS))
def test_reserved_word_with_trailing_tokens_exits_two(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    """The rule tests tokens[0], not the sole token: `gaveta ls links` is reserved.

    Without this, `gaveta ls links` would capture today and silently become
    `subcommand + argument` at Stage 2 — a breaking change.
    """
    assert main([name, "extra", "tokens"]) == 2
    assert f"'{name}' is a reserved command" in capsys.readouterr().err


def test_reserved_word_check_precedes_argument_parsing(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    """`gaveta ls --all` is reserved, not an argparse 'unrecognized argument'."""
    assert main(["ls", "--all"]) == 2
    assert "reserved command" in capsys.readouterr().err


def test_quoted_text_beginning_with_a_reserved_word_is_captured(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    """The counter-case. One argv element, so it is text, not a command."""
    assert main(["ls my files"]) == 0
    assert "ls my files" in capsys.readouterr().out


def test_reserved_word_is_capturable_after_a_double_dash(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    """The escape hatch the reserved-word message advertises."""
    assert main(["--", "ls"]) == 0
    assert "  raw      : ls" in capsys.readouterr().out


def test_lock_and_status_are_not_reserved(tty_stdin: _FakeStdin) -> None:
    """ADR-001: reserving them would invent vocabulary the plan does not contain."""
    assert "lock" not in SUBCOMMANDS
    assert "status" not in SUBCOMMANDS
    assert main(["lock"]) == 0


# --- The --json contract -----------------------------------------------------


def test_json_flag_emits_one_valid_object(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["x", "--json"]) == 0

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["raw"] == "x"
    assert out.count("\n") == 1


def test_json_output_validates_against_the_capture_schema(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    """The machine view must parse back into the model that produced it."""
    main(["ssh -L 5432:rds-qa:5432 jump-host", "--json"])

    restored = CaptureRequest.model_validate_json(capsys.readouterr().out)

    assert restored.raw == "ssh -L 5432:rds-qa:5432 jump-host"
    assert restored.type == "unknown"
    assert restored.tags == []


def test_json_flag_suppresses_the_human_view(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["x", "--json"])

    assert "[gaveta] would save:" not in capsys.readouterr().out


# --- argv defaulting and the entry point -------------------------------------


def test_main_reads_sys_argv_when_argv_is_none(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The console script calls `main()` with no arguments."""
    monkeypatch.setattr("sys.argv", ["gaveta", "from sys.argv"])
    monkeypatch.setattr("sys.stdin", _FakeStdin(isatty=True))

    assert main() == 0
    assert "from sys.argv" in capsys.readouterr().out


def test_version_flag_exits_zero(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    import gaveta

    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert gaveta.__version__ in capsys.readouterr().out


@pytest.mark.parametrize("token", ["-L", "--nope", "-v"])
def test_bare_dash_token_is_an_option_not_text(
    tty_stdin: _FakeStdin, token: str
) -> None:
    """A dash token with no space looks like an option to argparse, and it wins.

    This is shared with every parser (typer behaves the same). `--` is the escape.
    """
    with pytest.raises(SystemExit) as exit_info:
        main([token])

    assert exit_info.value.code == 2


def test_dash_text_containing_a_space_is_captured(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    """`gaveta "-L 5432"` already works: one argv element, and it is not an option."""
    assert main(["-L 5432:rds-qa"]) == 0
    assert "-L 5432:rds-qa" in capsys.readouterr().out


def test_double_dash_captures_any_leading_dash_text(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    """The escape hatch, for the tokens argparse would otherwise claim."""
    assert main(["--", "-L"]) == 0
    assert "  raw      : -L" in capsys.readouterr().out


def test_stdin_is_typed_as_a_text_stream() -> None:
    """Guard the injection point the tests rely on."""
    stream: TextIO = _FakeStdin("x")
    assert stream.read() == "x"
