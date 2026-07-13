"""The clipboard seam: a best-effort copy that never crashes.

No test touches a real clipboard — the module's `_copy_fn` indirection is replaced
with a fake, so both the success and the no-backend paths are driven
deterministically. The no-backend path is the CI reality (headless runners), and the
one the `-c` fallback rests on.
"""

import pytest

from gaveta import clipboard


def test_copy_returns_true_when_the_backend_accepts_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    landed: list[str] = []
    monkeypatch.setattr(clipboard, "_copy_fn", landed.append)

    assert clipboard.copy("payload") is True
    assert landed == ["payload"]


def test_copy_returns_false_when_no_backend_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A headless machine: pyperclip raises, and copy degrades to False, no crash."""

    def no_backend(_text: str) -> None:
        raise RuntimeError("no clipboard mechanism available")

    monkeypatch.setattr(clipboard, "_copy_fn", no_backend)

    assert clipboard.copy("payload") is False
