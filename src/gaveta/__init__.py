"""Gaveta — everything you need, right where you left it."""

from importlib.metadata import version

# Read from the installed distribution metadata so `pyproject.toml` stays the
# single source of truth. Note: the distribution name, not the import name.
__version__: str = version("gaveta-cli")

__all__ = ["__version__"]
