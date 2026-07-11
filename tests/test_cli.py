"""The capture path's resolution table: every input class has exactly one outcome.

`main(argv)` takes its arguments by injection, so these run in-process with no
`subprocess` and no real terminal. stdin is faked via monkeypatch, which exercises both
the tty and non-tty branches deterministically — the distinction that decides how
`gaveta` behaves on a CI runner.

Output is asserted through `--json` wherever the *content* matters: the machine view is
the stable contract, and pinning human strings here would make every wording tweak a
test edit. The human confirmation has its own tests in test_render.py.
"""

import contextlib
import io
import json
from typing import TextIO

import pytest

from gaveta.cli import main
from gaveta.commands import IMPLEMENTED, RESERVED, SUBCOMMANDS
from gaveta.models import ItemView


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


def _saved(capsys: pytest.CaptureFixture[str]) -> ItemView:
    """The `--json` payload of the capture that just ran, validated into the model."""
    return ItemView.model_validate_json(capsys.readouterr().out)


# --- Row 4: argument form ----------------------------------------------------


def test_argument_form_captures_and_exits_zero(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["test note"]) == 0

    out = capsys.readouterr().out
    assert "✓ saved" in out
    assert "id 1" in out


def test_argument_form_persists_the_raw_text(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["test note", "--json"]) == 0
    assert _saved(capsys).raw == "test note"


def test_argument_form_joins_multiple_tokens(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["hello", "world", "--json"]) == 0
    assert _saved(capsys).raw == "hello world"


def test_argument_form_never_reads_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lazy-stdin contract: reading it here hangs on an open pipe."""
    fake = _pipe(monkeypatch, "should not be read")

    assert main(["from argument"]) == 0
    assert fake.was_read is False


# --- Row 3: explicit stdin ---------------------------------------------------


def test_dash_reads_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _pipe(monkeypatch, "piped note\n")

    assert main(["-", "--json"]) == 0
    assert _saved(capsys).raw == "piped note"


def test_dash_with_empty_stdin_is_nothing_to_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pipe(monkeypatch, "")

    assert main(["-"]) == 2


# --- Row 5: bare pipe with content -------------------------------------------


def test_bare_pipe_captures_without_the_dash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _pipe(monkeypatch, "implicit\n")

    assert main(["--json"]) == 0
    assert _saved(capsys).raw == "implicit"


# --- Rows 6 & 7: empty input, on a pipe and on a tty -------------------------


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
    """Row 6. CI runners have non-tty stdin, so this is the path CI takes."""
    _pipe(monkeypatch, stdin_text)

    assert main([]) == 2

    err = capsys.readouterr().err
    assert "usage: gaveta" in err
    assert "nothing to capture" in err


def test_no_input_on_a_tty_exits_two(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    """Row 7. Same outcome as row 6: tty and non-tty behave identically."""
    assert main([]) == 2

    err = capsys.readouterr().err
    assert "usage: gaveta" in err
    assert "nothing to capture" in err


def test_empty_capture_writes_nothing_to_stdout(
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


# --- Row 2: reserved first token ---------------------------------------------


@pytest.mark.parametrize("name", sorted(RESERVED))
def test_reserved_word_alone_exits_two(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    assert main([name]) == 2

    err = capsys.readouterr().err
    assert f"'{name}' is a reserved command" in err
    assert f"Stage {RESERVED[name]}" in err


@pytest.mark.parametrize("name", sorted(RESERVED))
def test_reserved_word_with_trailing_tokens_exits_two(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    """The rule tests tokens[0], not the sole token: `gaveta f my query` is reserved."""
    assert main([name, "extra", "tokens"]) == 2
    assert f"'{name}' is a reserved command" in capsys.readouterr().err


@pytest.mark.parametrize("name", sorted(IMPLEMENTED))
def test_implemented_word_is_not_treated_as_reserved(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    """ls/show/retag/rm/export dispatch now; none may print the reserved-word message.

    `show`/`retag`/`rm` without an id raise argparse's own SystemExit, so this asserts
    the *reserved* path is gone rather than any particular exit code.
    """
    # show/rm without an id raise argparse's own SystemExit; that is still not the
    # reserved path, which is what this test is about.
    with contextlib.suppress(SystemExit):
        main([name])

    assert "reserved command" not in capsys.readouterr().err


def test_quoted_text_beginning_with_a_reserved_word_is_captured(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    """The counter-case. One argv element, so it is text, not a command."""
    assert main(["ls my files", "--json"]) == 0
    assert _saved(capsys).raw == "ls my files"


def test_reserved_word_is_capturable_after_a_double_dash(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    """The escape hatch the reserved-word message advertises."""
    assert main(["--json", "--", "ls"]) == 0
    assert _saved(capsys).raw == "ls"


def test_lock_and_status_are_not_reserved(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    """ADR-001: reserving them would invent vocabulary the plan does not contain."""
    assert "lock" not in SUBCOMMANDS
    assert "status" not in SUBCOMMANDS
    assert main(["lock", "--json"]) == 0
    assert _saved(capsys).raw == "lock"


# --- The --json contract -----------------------------------------------------


def test_json_flag_emits_one_valid_saved_object(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["x", "--json"]) == 0

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["raw"] == "x"
    assert payload["id"] == 1
    assert out.count("\n") == 1


def test_json_output_validates_against_the_item_view_schema(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    """The machine view must parse into the model that produced it — now `ItemView`."""
    main(["ssh -L 5432:rds-qa:5432 jump-host", "--json"])

    restored = _saved(capsys)

    assert restored.raw == "ssh -L 5432:rds-qa:5432 jump-host"
    assert restored.id == 1
    assert restored.tags == []


def test_json_flag_suppresses_the_human_confirmation(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["x", "--json"])

    assert "✓ saved" not in capsys.readouterr().out


# --- argv defaulting and leading-dash text -----------------------------------


def test_main_reads_sys_argv_when_argv_is_none(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The console script calls `main()` with no arguments."""
    monkeypatch.setattr("sys.argv", ["gaveta", "from sys.argv", "--json"])
    monkeypatch.setattr("sys.stdin", _FakeStdin(isatty=True))

    assert main() == 0
    assert _saved(capsys).raw == "from sys.argv"


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
    """A dash token with no space looks like an option to argparse, and it wins."""
    with pytest.raises(SystemExit) as exit_info:
        main([token])

    assert exit_info.value.code == 2


def test_dash_text_containing_a_space_is_captured(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    """`gaveta "-L 5432"` already works: one argv element, and it is not an option."""
    assert main(["-L 5432:rds-qa", "--json"]) == 0
    assert _saved(capsys).raw == "-L 5432:rds-qa"


def test_double_dash_captures_any_leading_dash_text(
    tty_stdin: _FakeStdin, capsys: pytest.CaptureFixture[str]
) -> None:
    """The escape hatch, for the tokens argparse would otherwise claim."""
    assert main(["--json", "--", "-L"]) == 0
    assert _saved(capsys).raw == "-L"


def test_stdin_is_typed_as_a_text_stream() -> None:
    """Guard the injection point the tests rely on."""
    stream: TextIO = _FakeStdin("x")
    assert stream.read() == "x"
