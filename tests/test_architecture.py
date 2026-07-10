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


def _python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


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
    """Containment, not just detection: the drawer stays on the machine."""
    tree = ast.parse(path.read_text(), filename=str(path))

    offending = _imported_names(tree) & _NETWORK_MODULES

    assert not offending, (
        f"{path.relative_to(SRC)} imports network modules: {offending}"
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
