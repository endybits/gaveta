"""Console entry point.

Capture resolves the input, hands it to `gaveta.core`, and prints the item that was
saved. The CLI is a client of the core, not the other way round: nothing here decides
what a capture *is*, only how it is spelled and how it is shown.

The parsing seam (argparse plus an explicit reserved-word check, rather than a CLI
framework) is recorded in ADR-001.
"""

import argparse
import sys
from collections.abc import Callable

from gaveta import __version__, core, gate
from gaveta.commands import implemented_head, reserved_head, reserved_message
from gaveta.db.session import session as db_session
from gaveta.exit_codes import ExitCode
from gaveta.gate import Verdict
from gaveta.render import render_blocked, render_json, render_saved
from gaveta.subcommands import DISPATCH

_STDIN_TOKEN = "-"

# What the tty prompt tells the user when a value is only *maybe* a secret.
_SUSPICIOUS_PROMPT = (
    "⚠ this looks like it might contain a secret.\n"
    "  [v]ault (refuse) · [r]edact · [s]ave anyway ? "
)

# Shown when a suspicious value arrives over a pipe, where we cannot prompt. Names the
# two escape hatches so a script is never left guessing (ADR-003).
_SUSPICIOUS_NON_TTY = (
    "✋ blocked: input may contain a secret, and there is no terminal to confirm.\n"
    "   Re-run in a terminal to choose, or keep it now with the secret masked:\n"
    "     gaveta --redact -"
)

_DESCRIPTION = "Capture text into your drawer, or manage what you have captured."

_EPILOG = (
    "Commands:  ls [type] · show <id> · rm <id> · export\n"
    "A bare dash token (-L) is read as an option; put it after `--` to capture it,\n"
    'e.g.  gaveta -- "-L". Quoted text containing a space ("ssh -L 5432") is fine.\n'
    "Reserved for later stages: retag, f, reindex, cred, daemon, ui."
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gaveta",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "text",
        nargs="*",
        help=f"text to capture; use {_STDIN_TOKEN!r} to read it from stdin",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_out",
        help="emit the saved item as one JSON object instead of the confirmation",
    )
    parser.add_argument(
        "--redact",
        action="store_true",
        help="mask any detected secret with [REDACTED] and save the rest",
    )
    parser.add_argument("--version", action="version", version=f"gaveta {__version__}")
    return parser


def _resolve_raw(
    tokens: list[str],
    read_stdin: Callable[[], str],
    stdin_isatty: bool,
) -> str | None:
    """Resolve the text to capture, or None when there is nothing to capture.

    stdin is read lazily: `read_stdin` is called only on the branches that need it.
    Reading it eagerly to decide the source makes `gaveta "text"` hang whenever
    stdin is an open pipe.

    Empty or whitespace-only input means *nothing to capture*, whether it arrived
    over a pipe or from a tty. That equivalence is what makes `gaveta` behave the
    same on a developer's terminal and on a CI runner, where stdin is never a tty.
    """
    if tokens == [_STDIN_TOKEN]:
        return read_stdin().strip() or None
    if tokens:
        return " ".join(tokens).strip() or None
    if not stdin_isatty:
        return read_stdin().strip() or None
    return None


def main(argv: list[str] | None = None) -> int:
    """Run the CLI, and return its exit code.

    Dispatch order, all keyed on the first token only (so `gaveta "ls my files"` stays
    text):

    1. An implemented subcommand (`ls`/`show`/`rm`/`export`) → its handler.
    2. A still-reserved word (`f`, `cred`, …) → usage, exit 2.
    3. Anything else → capture.
    """
    tokens = list(sys.argv[1:] if argv is None else argv)

    # Subcommands and reserved words are both checked before argparse, which would
    # otherwise swallow the leading token as capture text.
    implemented = implemented_head(tokens)
    if implemented is not None:
        return DISPATCH[implemented](tokens[1:])

    reserved = reserved_head(tokens)
    if reserved is not None:
        print(reserved_message(reserved), file=sys.stderr)
        return ExitCode.USAGE

    parser = _build_parser()
    args = parser.parse_args(tokens)

    # Whether a real person is at the keyboard, decided *before* stdin may be drained by
    # `_resolve_raw`. It is what tells the suspicious branch it may prompt.
    interactive = sys.stdin.isatty()

    raw = _resolve_raw(args.text, sys.stdin.read, sys.stdin.isatty())
    if raw is None:
        parser.print_usage(sys.stderr)
        print("\n[gaveta] nothing to capture.", file=sys.stderr)
        return ExitCode.USAGE

    return _capture(
        raw,
        redact=args.redact,
        json_out=args.json_out,
        interactive=interactive,
        prompt=_prompt_choice,
    )


def _prompt_choice() -> str:
    """Ask the [v/r/s] question and return the raw answer. `EOFError` → refuse.

    Isolated behind a name so the tests can inject a fake and drive every branch of the
    suspicious matrix without a real terminal — the same trick `_resolve_raw` uses for
    stdin. On EOF (piped stdin exhausted, `Ctrl-D`) we return `"v"`: never save on an
    answer that never came.
    """
    try:
        return input(_SUSPICIOUS_PROMPT)
    except EOFError:
        return "v"


def _capture(
    raw: str,
    *,
    redact: bool,
    json_out: bool,
    interactive: bool,
    prompt: Callable[[], str],
) -> int:
    """The capture path, gate and all. Returns the exit code.

    `--redact` pre-empts everything: it is the user declaring the choice, so it applies
    before the tty branch and saves the masked text (exit 0). Otherwise the verdict
    decides: `blocked` refuses (exit 3); `suspicious` prompts when a terminal is present
    and refuses otherwise; `clean` saves with no friction. Core re-enforces the block
    invariant regardless, so a bug here can never persist a known secret unredacted.
    """
    if redact:
        return _save(raw, redact=True, json_out=json_out)

    verdict = gate.scan(raw)
    if verdict.blocked:
        print(render_blocked(verdict), file=sys.stderr)
        return ExitCode.BLOCKED
    if verdict.suspicious:
        return _resolve_suspicious(
            raw, verdict, json_out=json_out, interactive=interactive, prompt=prompt
        )
    return _save(raw, redact=False, json_out=json_out)


def _resolve_suspicious(
    raw: str,
    verdict: Verdict,
    *,
    json_out: bool,
    interactive: bool,
    prompt: Callable[[], str],
) -> int:
    """A maybe-secret. Ask the human if we can; refuse with an escape hatch if not."""
    if not interactive:
        print(_SUSPICIOUS_NON_TTY, file=sys.stderr)
        return ExitCode.BLOCKED

    choice = prompt().strip().lower()[:1]
    if choice == "s":
        return _save(raw, redact=False, json_out=json_out)
    if choice == "r":
        return _save(raw, redact=True, json_out=json_out)
    # "v", empty, or anything unrecognized → refuse. Saving is opt-in, not the default.
    print(render_blocked(verdict), file=sys.stderr)
    return ExitCode.BLOCKED


def _save(raw: str, *, redact: bool, json_out: bool) -> int:
    """Persist through the core and print the confirmation. Exit 0.

    The `· redacted` marker reflects whether the stored text actually differs from what
    was typed — `--redact` on a clean note masks nothing, and claiming otherwise would
    mislead. The stored `raw` comes back on the view, so the comparison is exact.
    """
    with db_session() as session:
        saved = core.capture(raw, session=session, redact=redact)

    was_redacted = redact and saved.raw != raw
    view = (
        render_json(saved) if json_out else render_saved(saved, redacted=was_redacted)
    )
    sys.stdout.write(view if view.endswith("\n") else view + "\n")
    return ExitCode.OK
