# ADR-001 — CLI framework: `argparse`, not `typer`

- **Status:** Accepted
- **Date:** 2026-07-10
- **Stage:** 1 — Simulated capture (the walking skeleton)

## Context

Stage 1 fixes the capture contract for the whole project. Part of that contract is the shape of
the command line, and that shape is unusual:

```
gaveta "ssh -L 5432:rds-qa:5432 jump-host"   # free text, no verb
gaveta ls                                     # a named subcommand (Stage 2)
gaveta f "how did I reach qa?"                # another one (Stage 5)
```

A *free-text default command coexisting with named subcommands*. Capture is the hot path — it
must not require typing a verb — but `ls`, `show`, `rm`, `f` and the rest arrive in later stages.
Whatever we pick now, Stage 2 inherits. Choosing wrong means a rewrite at the exact moment the
CLI's public shape is first published.

`typer` is the fashionable default for new Python CLIs and was the obvious candidate. `argparse`
is the stdlib alternative. The choice was evaluated against four criteria named in the stage
spec: stdlib-only footprint, future subcommand ergonomics, testability, and `mypy --strict`
compatibility.

## Decision

**Use `argparse`, with an explicit reserved-word check before free-text capture.**

`rich` is adopted as a **render layer only**. It formats output; it has no say in argument
parsing. That separation is what keeps this decision reversible.

## Rationale

Both frameworks were probed against the real installed versions rather than judged by reputation.
Two findings decided it.

### 1. Typer cannot express "free-text default + subcommands"

The idiomatic attempt is a root callback with a variadic argument:

```python
@app.callback(invoke_without_command=True)
def root(ctx: typer.Context, text: Annotated[Optional[list[str]], typer.Argument()] = None) -> None: ...

@app.command("ls")
def ls_cmd() -> None: ...
```

Observed on `typer` 0.26.8:

```
$ python probe.py ls
capture: ls          # ← the subcommand was swallowed as capture text
```

The variadic `Argument` on the root callback consumes the token that would otherwise dispatch to
the subcommand. `ls` becomes unreachable. This is not a configuration mistake; it is what a
greedy positional means.

### 2. The standard workaround is broken on current Typer

The documented escape hatch subclasses `click.Group` to override `resolve_command`, then
reassigns `__class__` on the object returned by `typer.main.get_command(app)`. It works — on
older Typer. On a clean `uv pip install typer` (resolving `typer` 0.26.8):

```
$ python -c "import click"
ModuleNotFoundError: No module named 'click'
```

**Typer ≥0.26 no longer depends on `click`**; it ships its own parser via `typer-slim`. The
workaround now requires adding `click` as a *direct* dependency and betting that
`typer.main.get_command()` keeps returning click-compatible objects — a load-bearing bet on an
internal boundary the maintainers just moved. That is precisely the kind of debt a walking
skeleton must not take on.

### The four criteria

| Criterion | `argparse` | `typer` |
|---|---|---|
| Stdlib-only footprint | Yes — zero runtime deps. Keeps the local-first claim honest | Adds `typer` + `rich` + `shellingham` + `markdown-it-py` + `pygments` |
| Subcommand ergonomics | Explicit `SUBCOMMANDS` map checked before capture | **Cannot express the required shape** (findings 1–2) |
| Testability | `main(argv: list[str] \| None = None) -> int` — inject argv, no `subprocess` | `CliRunner` works, but the shape under test is unreachable |
| `mypy --strict` | Clean | Clean with `Annotated[...]` and `py.typed` — *not* a discriminator |

Worth recording honestly: **`mypy --strict` did not decide this.** An early probe reported
`untyped-decorator` against Typer, but that was an artifact of `typer` being absent from the
environment. Re-run in a venv with `typer` installed, the `Annotated[...]` style passes strict
mode with no errors — Typer ships `py.typed`. The criterion was a wash, and the ADR says so
rather than stacking a false argument onto a conclusion already reached on other grounds.

Leading-dash content (`gaveta "-L 5432"`) fails identically on **both** frameworks: a bare `-L`
is an unrecognized option either way. The remedy is `gaveta -- "-L …"` or stdin. Also not a
discriminator — a README note, not a code path.

## Consequences

**We accept** an explicit `SUBCOMMANDS` mapping in `gaveta/commands.py`, checked before free-text
capture. This is a cost, and it is the point: it makes visible an ambiguity Typer papers over.
`gaveta ls` is a command; `gaveta "ls my files"` is text. Someone has to decide that, and now the
decision has a name and a test.

**We accept** hand-writing `--help` output that Typer would generate. At the current surface —
one default command and a `--json` flag — this is a few lines.

**We gain** a `main(argv) -> int` entry point that tests call directly, zero runtime dependencies
from the CLI layer, and no exposure to Typer's internal churn.

**Reserved vocabulary.** The reserved set is fixed now at the **10 commands `IMPLEMENTATION_PLAN.md`
actually grounds**, not just the ones Stage 2 needs. Reserving only `ls`/`show`/`rm` would replay
this same dilemma at Stage 5 the first time someone captures the word `f`.

| Command | Lands in |
|---|---|
| `ls`, `show`, `rm`, `export` | Stage 2 |
| `retag` | Stage 4 |
| `f`, `reindex` | Stage 5 |
| `cred` | Stage 6 (Stage 3 only references it in a message) |
| `daemon` | Stage 7 |
| `ui` | Stage 8 |

`cred` is mapped to Stage 6, where it is actually implemented; Stage 3 merely names it in the
secret-gate block message. It is one command, not two.

The check inspects **`tokens[0]` only**. `gaveta ls`, `gaveta ls links`, and `gaveta ls --all` are
all reserved; only a quoted single argv element (`gaveta "ls my files"`) is text. Without the
first-token rule, `gaveta ls links` would capture today and silently become `subcommand + argument`
at Stage 2 — a breaking change, which is the debt the reservation policy exists to prevent.

**Deliberately not reserved: `lock` and `status`.** Both were proposed during review. Neither
appears in `IMPLEMENTATION_PLAN.md` as a `gaveta <word>`: `status` exists only as
`gaveta daemon status`, a sub-subcommand already covered by reserving `daemon`, and `lock` appears
nowhere at all. Reserving them would invent vocabulary the spec does not contain, violating this
project's spec-before-implementation rule. The omission is recorded here so it is a decision, not
an oversight. If a future stage introduces them, that stage reserves them — plan first.

## Revisiting this

Reverse this decision if Typer gains first-class support for a default free-text command, or if
the CLI surface grows enough that hand-written help becomes a real maintenance burden. Because
parsing and rendering are separate (`rich` never touches argv), swapping the parser would touch
`cli.py` and `commands.py` and nothing else.
