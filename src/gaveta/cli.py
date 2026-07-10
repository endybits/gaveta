"""Console entry point.

A stub for Stage 0. The real CLI — argument parsing, the capture flow, and the
framework choice recorded in ADR-001 — arrives in Stage 1.
"""

from gaveta import __version__


def main() -> None:
    """Print the installed version."""
    print(f"gaveta {__version__}")
