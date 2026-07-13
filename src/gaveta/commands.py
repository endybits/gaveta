"""Reserved command vocabulary — the seam where subcommands will live.

Stage 1 implements none of these, but it reserves all of them. The alternative —
reserving only what Stage 2 needs — replays the same dilemma at Stage 5 the first
time someone captures the bare word ``f``, and turns `gaveta ls links` from a
capture into a subcommand invocation: a silent breaking change.

See docs/adr/ADR-001-cli-framework.md.
"""

from collections.abc import Mapping
from types import MappingProxyType

# The implemented subcommands. They dispatch; they are no longer reserved words that
# exit 2. `retag` joined here in Stage 4; `f` and `reindex` in Stage 5. The set is a
# frozenset because membership is all the CLI asks.
IMPLEMENTED: frozenset[str] = frozenset(
    {"ls", "show", "rm", "export", "retag", "f", "reindex"}
)

# The rest — mapped to the stage that implements each. Read-only so a caller cannot
# mutate it. A word leaves this table for `IMPLEMENTED` when its stage lands.
#
# Deliberately absent: `lock` and `status`. Neither appears in the plan as a
# `gaveta <word>` — `status` exists only as `gaveta daemon status`, already
# covered by reserving `daemon`. Reserving them would invent vocabulary the spec
# does not contain. ADR-001 records this.
RESERVED: Mapping[str, int] = MappingProxyType(
    {
        "cred": 6,
        "daemon": 7,
        "ui": 8,
    }
)

# The whole grounded vocabulary, implemented or not. A capture of any of these bare
# words is a subcommand invocation or a reserved-word error — never text — so that
# `gaveta ls links` cannot silently change meaning between stages (ADR-001).
SUBCOMMANDS: frozenset[str] = IMPLEMENTED | frozenset(RESERVED)


def implemented_head(tokens: list[str]) -> str | None:
    """Return the implemented subcommand at the head of ``tokens``, if any.

    First token only, the same rule `reserved_head` uses: `gaveta ls links` dispatches
    to `ls`, while the single quoted argv element `gaveta "ls my files"` is text.
    """
    if tokens and tokens[0] in IMPLEMENTED:
        return tokens[0]
    return None


def reserved_head(tokens: list[str]) -> str | None:
    """Return the not-yet-implemented reserved command at the head of ``tokens``.

    Only ``tokens[0]`` is inspected; trailing tokens are ignored. So `gaveta f`,
    `gaveta f my query` and `gaveta f --all` are all reserved, while the single
    quoted argv element in `gaveta "f my files"` is ordinary text.
    """
    if tokens and tokens[0] in RESERVED:
        return tokens[0]
    return None


def reserved_message(name: str) -> str:
    """Explain that ``name`` is reserved, and say when it arrives."""
    stage = RESERVED[name]
    return (
        f"[gaveta] '{name}' is a reserved command (lands in Stage {stage}).\n"
        f'         To capture it as text instead:  gaveta -- "{name}"'
    )
