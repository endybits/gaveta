"""Architecture invariants, enforced by the suite rather than by good intentions.

These are the boundaries CLAUDE.md calls non-negotiable. A test is what makes "stays
local" a property the codebase cannot lose by accident.
"""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src" / "gaveta"

# Modules that reach the network. Nothing under src/gaveta may import one: the whole
# design assumes the drawer never leaves the machine (CLAUDE.md, ADR-002). Stage 7's
# daemon binds to localhost via a dependency this list will then permit explicitly — but
# it is not here yet, and fencing it now is the point.
_NETWORK_MODULES = {
    "socket",
    "http",
    "httplib",
    "urllib",
    "urllib2",
    "httpx",
    "requests",
    "aiohttp",
    "ftplib",
    "smtplib",
    "telnetlib",
    "websocket",
    "websockets",
}

# The single, scoped exception (ADR-004). `gaveta.brain` talks to a local Ollama over
# HTTP, so `httpx` is importable there — and *only* there. Every other module keeps the
# full ban above, `httpx` included, so a stray `import httpx` in core or the CLI still
# fails the build. The exception is import-name scope; the localhost-only guarantee is
# enforced separately, below, because the AST sees `import httpx`, not the URL it dials.
_BRAIN = "brain"
_BRAIN_ALLOWED = {"httpx"}

# Hosts a brain URL literal may name. Anything else is a non-local endpoint smuggled
# into the one module allowed an HTTP client — layer-4 containment exists to forbid it.
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]")


def _python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _is_brain(path: Path) -> bool:
    return _BRAIN in path.relative_to(SRC).parts


def _banned_modules_for(path: Path) -> set[str]:
    """The network-import ban set that applies to one file.

    Every module gets the full ban; `gaveta.brain` gets it minus its scoped exception.
    """
    if _is_brain(path):
        return _NETWORK_MODULES - _BRAIN_ALLOWED
    return _NETWORK_MODULES


def _imported_names(tree: ast.AST) -> set[str]:
    """Every top-level module name imported in `tree`."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_there_are_source_files_to_scan() -> None:
    """A guard on the guard: an empty glob would make every scan below pass vacuous."""
    assert _python_files(), f"no python files found under {SRC}"


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.relative_to(SRC)))
def test_no_module_imports_a_network_library(path: Path) -> None:
    """Containment, not just detection: the drawer stays on the machine.

    `gaveta.brain` may import `httpx` to reach a local Ollama (ADR-004); every other
    module is still banned from all of `_NETWORK_MODULES`, `httpx` included.
    """
    tree = ast.parse(path.read_text(), filename=str(path))

    offending = _imported_names(tree) & _banned_modules_for(path)

    assert not offending, (
        f"{path.relative_to(SRC)} imports network modules: {offending}"
    )


def test_only_brain_may_import_httpx() -> None:
    """State the scoped exception as its own assertion, not just a subtraction above.

    `httpx` is the one network module `gaveta.brain` is allowed; no file outside `brain`
    may import it. This is the exact seam the daemon (Stage 7) will widen — with its own
    ADR — so pin it down now.
    """
    for path in _python_files():
        if _is_brain(path):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        assert "httpx" not in _imported_names(tree), (
            f"{path.relative_to(SRC)} imports httpx; only gaveta.brain may (ADR-004)"
        )


def test_brain_names_no_non_localhost_url() -> None:
    """Import scope is necessary but not sufficient — the AST sees `import httpx`, not
    the URL it dials. So the one module holding an HTTP client may name only a local
    host: any `http(s)://…` literal in `brain` must point at localhost. A non-local
    default URL anywhere in `brain` fails the build (ADR-004, layer-4 containment)."""
    brain_files = [p for p in _python_files() if _is_brain(p)]
    for path in brain_files:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            text = node.value
            if "://" not in text:
                continue
            assert any(host in text for host in _LOCAL_HOSTS), (
                f"{path.relative_to(SRC)} names a non-localhost URL {text!r}; "
                "brain may only ever dial the local machine (ADR-004)"
            )


def test_no_get_secret_symbol_exists_yet() -> None:
    """The absence of a secret-reading API *is* the security property (CLAUDE.md).

    Stage 6 introduces the VaultProvider protocol with exactly `exists`,
    `copy_to_clipboard`, `open_in_app` — and no `get_secret`. Nothing in Stage 2 should
    define one either; this fails the suite the moment such a symbol appears.
    """
    for path in _python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                assert "get_secret" not in node.name, (
                    f"{path.relative_to(SRC)} defines {node.name!r}; "
                    "a secret-reading API must never exist (CLAUDE.md)"
                )
