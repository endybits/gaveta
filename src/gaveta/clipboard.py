"""The clipboard seam — one place that touches `pyperclip`, with a print fallback.

`gaveta f -c` copies the best hit's payload to the clipboard. But a headless machine
(a CI runner, a bare server) has no clipboard backend, and `pyperclip` raises there.
So the copy is a *best effort*: `copy(text)` returns whether it landed on the
clipboard, and the caller prints the payload when it did not. That fallback is not an
error path — it is the CI path, and the one exercised by the tests, which never touch
a real clipboard.

Isolating `pyperclip` here keeps the dependency out of the command handlers and gives
the tests a single seam to fake.
"""

from collections.abc import Callable

import pyperclip

# The one call into pyperclip, as a module-level indirection the tests replace.
# pyperclip raises `PyperclipException` when no backend is found; catching broadly
# keeps a clipboard quirk from ever crashing a search.
_copy_fn: Callable[[str], None] = pyperclip.copy


def copy(text: str) -> bool:
    """Put `text` on the clipboard. Returns whether it worked.

    `False` means no clipboard backend was available (headless), not a crash — the
    caller prints the payload instead. Any pyperclip failure degrades to `False`.
    """
    try:
        _copy_fn(text)
    except Exception:  # noqa: BLE001 — a missing backend must never crash a search
        return False
    return True
