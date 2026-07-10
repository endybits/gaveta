# ADR-003 — Secret gate: exit code 3, block-by-default under non-tty, spans on the verdict

- **Status:** Accepted
- **Date:** 2026-07-10
- **Stage:** 3 — Secret gate (deterministic detector)

## Context

Stage 3 makes true the promise the README has printed since Stage 1: *secrets never enter
Gaveta*. A deterministic detector, `gate.scan(raw) -> Verdict`, runs at the very front of the
capture pipeline — before persistence, and before any model in later stages. Known-format
secrets (AWS keys, GitHub/Slack/Stripe tokens, PEM blocks, `user:pass@` URLs, JWTs) are
rejected outright; high-entropy or context-flagged values are *suspicious* and get a human
in the loop.

Three decisions have to be settled before the gate is wired, and each outlives the stage:

1. **What exit code does a blocked capture return?** Today `2` is overloaded across empty
   input, reserved words, bad arguments, and argparse's own parse errors. A script that wraps
   `gaveta` must be able to tell "you typed nothing" from "that was a secret, and it was
   refused" — they are different failure classes and call for different handling.
2. **What happens when the interactive confirmation cannot run?** The `suspicious` tier asks
   the human `[v]ault / [r]edact / [s]ave anyway`. That prompt is impossible under a pipe or
   in CI, where stdin is never a tty (Stage 1's lesson). The behavior in that cell of the
   matrix is a security decision, not an ergonomic afterthought.
3. **What shape is the `Verdict`, and does it carry *where* the secret is?** `--redact` has to
   replace the secret with `[REDACTED]`, the tty prompt wants to highlight it, and the block
   message wants to name it. Whether these share one source of truth or each re-derive it
   determines whether they can drift.

The gate itself is *core*: `scan` and `redact` are pure functions that know nothing of argv, a
terminal, or an exit code — the same discipline the rest of `gaveta.core` follows. The exit
code and the prompt are *interface* concerns and live in the CLI. This ADR records the three
decisions above; the honest-limits framing and the four-layer defense model live in
[`docs/security-model.md`](../security-model.md).

The Stage 4 model-choice record, informally earmarked as ADR-003 during Stage 2, becomes
**ADR-004**. An ADR is numbered when it is written, not when it is imagined — the same rule
ADR-002 invoked when it took the number earmarked for the model choice.

## Decision 1 — A blocked capture exits `3`

**A capture refused because it contains a secret returns exit code `3`, distinct from the `2`
that every existing usage/parse failure returns.**

The exit-code table, which this stage makes authoritative:

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | not found (`show <missing>`) |
| `2` | usage: empty input, reserved word, unknown `ls` type, argparse parse error |
| `3` | **blocked: a secret was detected and not saved** |

`3` is the next contiguous integer; it collides with nothing argparse (`2`) or the BSD
`sysexits.h` convention uses at the low end, and it reads cleanly as "one worse than a usage
error." A blocked secret is emphatically *not* a usage error: the input was well-formed and
understood, and refused on policy. Folding it into `2` would make
`gaveta "$SECRET" || handle_empty_input` do the wrong thing.

This stage also introduces the project's **first named exit codes** — an `ExitCode(IntEnum)`
in `gaveta/exit_codes.py` (`OK=0, NOT_FOUND=1, USAGE=2, BLOCKED=3`). Until now the codes were
magic literals scattered across `cli.py` and `subcommands.py`; adding a fourth without naming
it would leave four call sites asserting `3` means the same thing by coincidence. Naming them
is a behavior-preserving refactor that lands as its own commit *before* the gate is wired, so
the rename diff and the semantics diff stay separate.

## Decision 2 — Under a non-tty, a suspicious value is blocked; the escape hatch is `--redact`

**When `scan` returns `suspicious` and no tty is available to run the confirmation prompt,
Gaveta blocks (exit `3`) and names the escape hatches, rather than saving silently or hanging
on input that can never arrive. There is no `--allow-suspicious` flag.**

The complete matrix:

| Verdict | tty | Behavior |
|---|---|---|
| `blocked` (known format) | tty | blocked, exit `3`. Message names what was detected and points to the vault flow (Stage 6, *upcoming*). No prompt — a known-format secret is not a judgment call. |
| `blocked` (known format) | non-tty | blocked, exit `3`. Identical. A pipe cannot rescue a known secret. |
| `suspicious` (entropy / context) | tty | prompt `[v]ault / [r]edact / [s]ave anyway`. `v` (or EOF / `Ctrl-C` / a bare Enter) refuses, exit `3`; `r` redacts and saves, exit `0`; `s` saves raw, exit `0`. |
| `suspicious` (entropy / context) | non-tty | blocked, exit `3`. Cannot prompt, so refuse. Message names two escape hatches: re-run in a terminal, or `gaveta --redact -`. Never saves silently; never hangs. |
| `clean` | either | save, exit `0`, no prompt. The zero-friction promise. |

`--redact` is a caller pre-declaring the choice, so it applies *before* the tty branch and
short-circuits the prompt in every case: `suspicious`/`blocked` under `--redact`, tty or not,
redacts and saves at exit `0`. It is precisely the escape hatch the non-tty refusal message
advertises.

**Why the default is *block*, not *save*.** The alternative — saving a suspicious value when we
cannot ask — quietly persists exactly the class of value the gate exists to catch, the moment
capture happens in a script or CI. Blocking loses nothing recoverable (the user re-runs, or
pipes through `--redact`) and never persists a secret behind the user's back. On a pipe the
choice is between "refuse and tell them how to proceed" and "save something we flagged as
possibly a secret without a human ever seeing the flag"; the first is the only one consistent
with *secrets never enter Gaveta*.

**Why no `--allow-suspicious` flag.** `--redact` already *is* the non-tty escape hatch for a
value worth keeping, and it keeps the promise while doing so — the `[REDACTED]` text lands, the
raw secret never does. A flag that saves the *raw* suspicious value verbatim in a script is a
footgun with a handle: `some_cmd | gaveta --allow-suspicious -` would persist a real secret
that merely lacks a known format, which is the exact hole containment (layer 4) exists to
cover. If a user genuinely wants the raw value saved, the honest path is a real terminal and an
explicit `s` keystroke — a human looking at the highlighted value and choosing. The non-tty
suspicious escape hatches are therefore exactly two: confirm interactively, or redact.

## Decision 3 — `Verdict` is a frozen dataclass carrying spans

**`Verdict` is a `frozen=True` dataclass with a `Level` enum and a tuple of `Finding`s, each
carrying the character span and rule of one match. It is not a pydantic model, and it never
crosses the `--json` wire.**

```python
class Level(enum.Enum):
    clean = "clean"
    suspicious = "suspicious"
    blocked = "blocked"

@dataclass(frozen=True)
class Finding:
    rule: str      # "aws_access_key", "jwt", "high_entropy", "context_word:password"
    start: int     # char offset into raw
    end: int
    label: str     # human phrase: "an AWS access key", "a high-entropy value"

@dataclass(frozen=True)
class Verdict:
    level: Level
    findings: tuple[Finding, ...] = ()
```

`Verdict` is *internal*. Only `ItemView` crosses the `--json` boundary, and its snapshot is
unchanged this stage, so the verdict earns no pydantic validation and no JSON Schema. A frozen
dataclass plus a stdlib enum is lighter, is trivially `mypy --strict`-clean, and matches how
the codebase already reaches for stdlib enums (`ItemType` is a `StrEnum`).

**It carries spans so redaction, highlighting, and messaging share one source of truth.**
`redact(raw, verdict)` replaces exactly the `Finding` spans with `[REDACTED]` — applied
right-to-left so earlier offsets stay valid — the tty prompt can highlight those same spans,
and the block message names the rule via `label`. The alternative, a `level`-only verdict that
`--redact` re-scans to locate spans, runs the detector twice and lets detection and redaction
drift: a pattern tightened in one place and not the other would redact the wrong bytes. One
scan, one set of spans, every consumer reading from it.

### Entropy heuristic (the numbers behind the `suspicious` tier)

Recorded here because the thresholds are a judgment the doc's honesty section leans on. Two
independent triggers raise `suspicious`, never `blocked` — the entropy tier is a guess, and a
guess gets the confirm path:

- **High-entropy token:** any whitespace/quote-delimited token of length ≥ 20 whose Shannon
  entropy is ≥ 4.0 bits/char. 4.0 sits deliberately at the git-SHA boundary (16-symbol hex
  caps at 4.0 bits/char), so a 40-hex SHA or a UUID rates *at or just below* the line —
  `suspicious` at worst, never `blocked` — while base64 of random bytes (~5.5–6.0) clears it.
  The length floor of 20 keeps ordinary long English/Spanish words below the trigger.
- **Context word beside a value:** a bilingual list (`password`, `passwd`, `pwd`, `secret`,
  `token`, `api_key`, `apikey`, `access_key`, `auth`, `bearer`, `clave`, `contraseña`,
  `secreto`, `credencial`) in the form `word: value` / `word = value` / `word=value` with a
  value of length ≥ 8. This is what flags `MargaritaVerde2024!` — a real password with no
  detectable format — *as suspicious*, so the human gets the confirm path.

The list is bilingual because the user's captures mix English and Spanish; it is a hardcoded,
commented `frozenset` in `gate.py`, maintained by editing that constant. No config file this
stage (that is fenced out of Stage 3). The false-positive stance is explicit: a SHA or UUID
*may* rate `suspicious`, which is acceptable **only because saving it is one keystroke** at the
prompt — never a silent block, never a lost capture. Plain prose rates `clean`.

## Consequences

**We accept** a fourth exit code and the first exit-code enum. Wrapper scripts that treated any
non-zero exit as "usage error" now see `3` for a blocked secret; that is the distinction the
decision exists to give them, and it is documented in the table above and in the README.

**We accept** that a suspicious value cannot be saved from a pipe without an explicit
`--redact`. A script that wants to capture a high-entropy string it knows is benign (a build
hash, say) must either run in a terminal and press `s`, or accept the `[REDACTED]` form. This
is friction by design, on the rare path, in service of never persisting a flagged secret
unseen.

**We gain** a gate that is pure core: `scan` and `redact` know nothing of a terminal, so the
daemon (Stage 7) and the MCP server (Stage 9) inherit the same enforcement without a rewrite,
and the block invariant — *nothing blocked reaches disk unredacted* — lives in `core.capture()`
where every interface must pass through it.

**We gain** one source of truth for where each secret is. Redaction, the tty highlight, and the
block message all read the same `Finding` spans, so they cannot disagree about what was
detected or where.

**We give up** the `--allow-suspicious` convenience deliberately. Saving a raw suspicious value
in a script is available only by pressing `s` at a real prompt — a human decision, not a flag —
which is the point.

## Revisiting this

Revisit the non-tty policy only if a concrete, safe use case for saving raw suspicious values
in automation appears — and even then, prefer widening `--redact`'s behavior or a scoped,
loudly-named flag over a blanket `--allow-suspicious`. The default (block) does not move.

Revisit the exit code only on a move to a CLI framework that owns its own exit-code scheme; the
*distinction* between usage and blocked survives any such move.

Revisit `Verdict`'s shape only if it needs to cross a serialization boundary (an HTTP response,
an MCP payload). At that point it grows a pydantic mirror or a `to_dict`, but the internal
dataclass — with its spans — stays the detector's own representation.
