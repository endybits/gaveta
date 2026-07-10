"""The CLI's exit codes, named once so every caller agrees on what each means.

Until Stage 3 these were magic integers returned inline across `cli.py` and
`subcommands.py`. A blocked-secret capture (Stage 3) needed a *fourth* code, distinct
from the `2` that already covered four unrelated usage failures — and adding it as one
more bare literal would leave call sites asserting a number's meaning by coincidence.

`IntEnum` so a handler can still `return ExitCode.OK` where the signature says `-> int`,
and so `sys.exit`/`SystemExit` treat it as the integer it is. See ADR-003.
"""

import enum


class ExitCode(enum.IntEnum):
    """What `gaveta` returns to the shell, and what each value means to a script."""

    OK = 0
    # `show <id>` for an id that is not there. Absence a reader asked for is a failure.
    NOT_FOUND = 1
    # The overloaded one, by design: empty input, a reserved word, an unknown `ls`
    # type, and argparse's own parse errors all mean "you did not ask for something
    # I can do." A script distinguishes them by message, not by code.
    USAGE = 2
    # A secret was detected and the capture was refused. A different failure class from
    # USAGE — the input was understood and rejected on policy — so it gets its own code
    # a wrapper can branch on. See ADR-003 and docs/security-model.md.
    BLOCKED = 3
