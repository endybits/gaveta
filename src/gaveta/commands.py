"""Reserved command vocabulary — the seam where subcommands will live.

Stage 1 implements none of these, but it reserves all of them. The alternative —
reserving only what Stage 2 needs — replays the same dilemma at Stage 5 the first
time someone captures the bare word ``f``, and turns `gaveta ls links` from a
capture into a subcommand invocation: a silent breaking change.

See docs/adr/ADR-001-cli-framework.md.
"""

from collections.abc import Mapping
from types import MappingProxyType

# Every `gaveta <word>` that IMPLEMENTATION_PLAN.md grounds, mapped to the stage
# that implements it. Read-only so a caller cannot mutate the vocabulary.
#
# Deliberately absent: `lock` and `status`. Neither appears in the plan as a
# `gaveta <word>` — `status` exists only as `gaveta daemon status`, already
# covered by reserving `daemon`. Reserving them would invent vocabulary the spec
# does not contain. ADR-001 records this.
SUBCOMMANDS: Mapping[str, int] = MappingProxyType(
    {
        "ls": 2,
        "show": 2,
        "rm": 2,
        "export": 2,
        "cred": 6,
        "retag": 4,
        "f": 5,
        "reindex": 5,
        "daemon": 7,
        "ui": 8,
    }
)


def reserved_head(tokens: list[str]) -> str | None:
    """Return the reserved command at the head of ``tokens``, if any.

    Only ``tokens[0]`` is inspected; trailing tokens are ignored. So `gaveta ls`,
    `gaveta ls links` and `gaveta ls --all` are all reserved, while the single
    quoted argv element in `gaveta "ls my files"` is ordinary text.
    """
    if tokens and tokens[0] in SUBCOMMANDS:
        return tokens[0]
    return None


def reserved_message(name: str) -> str:
    """Explain that ``name`` is reserved, and say when it arrives."""
    stage = SUBCOMMANDS[name]
    return (
        f"[gaveta] '{name}' is a reserved command (lands in Stage {stage}).\n"
        f'         To capture it as text instead:  gaveta -- "{name}"'
    )
