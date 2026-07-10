# Gaveta's security model

> **Secrets never enter Gaveta.** That is the promise. This document explains how it is
> kept, and — just as important — where it can fail.

Gaveta is a drawer for the things a developer needs close at hand: commands, links,
snippets, notes. Some of those live dangerously close to secrets. A connection string is
a URL with a password in it; a deploy note has an access key three words from a hostname.
So a knowledge tool that captures freely has to decide, on every capture, whether it is
about to store a secret — and it has to decide *before* the secret is written anywhere.

The design is **four layers**, defense in depth. This is deliberate: no single layer is
trusted to be perfect, because none is.

| Layer | What it does | Status |
|---|---|---|
| 1 · Deterministic gate | Regexes for known secret formats reject on sight | **Stage 3 (here)** |
| 2 · Contextual / model | A local model flags what the format rules miss | Stage 4 |
| 3 · Human confirmation | Ambiguous cases ask you before saving | **Stage 3 (here)** |
| 4 · Containment | Everything stays local; outbound paths re-scan | Architecture + Stage 9 |

Stage 3 delivers **layers 1 and 3**. Layer 4 already exists — it *is* the local-first
architecture — and layer 2 arrives with the local model in Stage 4.

## Layer 1 — the deterministic gate

Before anything else touches a capture — before it is classified, before it is stored,
before, from Stage 4 on, any model sees it — `gate.scan(raw)` runs. It is the *first* step
of the capture pipeline, and that order is the security property, asserted by a test that a
blocked capture leaves the database untouched.

The gate matches **known secret formats** by regex, patterns borrowed in shape (not code)
from [gitleaks](https://github.com/gitleaks/gitleaks) and
[trufflehog](https://github.com/trufflesecurity/trufflehog):

- **AWS access keys** — `AKIA…`, `ASIA…`, and the other IAM entity prefixes.
- **GitHub tokens** — `ghp_` / `gho_` / `ghu_` / `ghs_` / `ghr_`.
- **Slack tokens** — `xoxb-` / `xoxp-` / `xoxa-` / `xoxr-`.
- **Stripe secret keys** — `sk_live_` / `rk_live_` (test keys are not guarded).
- **Private keys** — the `-----BEGIN … PRIVATE KEY-----` PEM header.
- **Connection-string passwords** — `scheme://user:pass@host`.
- **JWTs** — the three-segment `eyJ…​.eyJ…​.…` shape.

A match is **blocked**: the capture is refused with exit code `3`, and a message names what
was detected and points at the vault flow (which lands for real in Stage 6). Nothing is
written. A known-format secret is not a judgment call, so the gate does not ask — it refuses.

```
$ gaveta "deploy key: AKIAIOSFODNN7EXAMPLE"
✋ blocked: input contains what looks like an AWS access key.
   Secrets never enter Gaveta. Store it in your vault and save a reference
   instead — that flow lands in a later release (gaveta cred --new).
   To keep this capture now with the secret masked:  gaveta --redact
```

## Layer 3 — human confirmation for the ambiguous middle

Not every secret has a format. `MargaritaVerde2024!` is a perfectly good password and
matches no regex on earth. For that middle ground the gate raises **suspicious**, never
*blocked* — because a guess deserves a human, not a refusal. Two signals raise it:

- **High entropy** — a long token (≥ 20 chars) whose Shannon entropy clears ~4.0 bits per
  character. Random API keys and base64 blobs clear it; a git SHA or a UUID sits just below,
  so those benign values stay quiet.
- **A context word beside a value** — `password:`, `token=`, `clave:`, `contraseña:`… The
  list is bilingual (English and Spanish) because real captures mix the two. This is what
  catches `MargaritaVerde2024!` — not its shape, but the `password:` in front of it.

When a suspicious value is captured **at a terminal**, Gaveta asks:

```
⚠ this looks like it might contain a secret.
  [v]ault (refuse) · [r]edact · [s]ave anyway ?
```

- **v** (also the default on a bare Enter, EOF, or `Ctrl-D`) — refuse, exit `3`. Saving is
  opt-in; a fat-fingered Enter never persists a secret.
- **r** — redact the detected span to `[REDACTED]` and save the rest.
- **s** — save it verbatim. You looked at it and decided; that is a human choice, not the
  tool's.

**Under a pipe or in CI there is no terminal to ask.** The prompt cannot run, so Gaveta
*blocks* rather than guess — it never saves a flagged value unseen, and it never hangs
waiting for input that cannot come:

```
$ echo "password: MargaritaVerde2024!" | gaveta -
✋ blocked: input may contain a secret, and there is no terminal to confirm.
   Re-run in a terminal to choose, or keep it now with the secret masked:
     gaveta --redact -
```

The two escape hatches are named right there: re-run interactively, or `--redact`. There
is deliberately **no `--allow-suspicious` flag** — a switch that saved raw suspicious values
in automation would be a quiet way to persist exactly the thing this layer exists to catch.
Keeping a suspicious value raw requires a real terminal and an explicit `s`.

### `--redact`

`--redact` masks every detected span with `[REDACTED]` and saves what remains. It works on
any capture, from any source, and is the one path by which a *detected* secret may be stored
— because the secret itself is not: the `[REDACTED]` text is. The invariant the code
enforces is therefore precise:

> **Nothing blocked ever reaches disk *unredacted*.**

`--redact` is checked before the block, so `gaveta --redact "…AKIA…"` saves the masked note
at exit `0` rather than refusing. A round-trip test reads the raw bytes of every file under
`~/.gaveta` — the database *and* any SQLite `-wal` / `-journal` sidecar — and asserts the
secret substring appears in none of them.

## Layer 4 — containment (assume the detector leaks)

**No format detector has 100% recall.** This is not a limitation to apologize for; it is the
premise the rest of the design is built on. `MargaritaVerde2024!` proves it — a real secret
the regexes cannot see, rescued only because a keyword happened to sit beside it. Some
secret, someday, will have neither a format nor a telltale word, and it will get saved.

So containment matters as much as detection:

- **Everything is local.** The drawer is a SQLite file at `~/.gaveta/gaveta.db` (overridable
  via `GAVETA_HOME`). Nothing is sent to any external API — a fact enforced by a test that
  fails the build if any module imports a network library.
- **No secret-reading API exists.** From Stage 6, credentials live in your real vault
  (Bitwarden, KeePassXC) and Gaveta stores only *references*. Resolving one sends the secret
  straight from the vault to your clipboard; it never crosses Gaveta's return values, stdout,
  logs, database, or model context. There is deliberately no `get_secret()` function — a test
  fails the suite if such a symbol ever appears. The absence of the API *is* the property.
- **Outbound paths re-scan.** The Stage 9 MCP server applies a second redaction pass over
  every payload it emits, reusing this stage's exact corpus — a second chance to catch what
  the first pass missed before anything leaves the machine.

A secret that slips past layer 1 is caught by layer 2 or a human at layer 3; one that slips
past all three still cannot leave your machine, because layer 4 gives it nowhere to go.

## Honest limits

- **Format detection is not complete.** New token formats appear; the ruleset is a living
  constant, not a guarantee. A secret in an unknown format is invisible to layer 1.
- **The entropy heuristic trades recall for quiet.** The threshold sits deliberately at the
  git-SHA boundary so ordinary hashes and IDs do not nag you. That same choice means a
  *short* secret, or a low-entropy one, can pass as clean.
- **`s` trusts you.** Save-anyway exists because sometimes you really do want to keep a
  high-entropy string. It is a loaded footgun by design, behind an explicit keystroke at a
  real terminal.
- **This is capture hygiene, not a secrets manager.** Gaveta keeps secrets *out*; it does
  not keep them *safe*. That job belongs to your vault, which is where layer 4 sends you.

The honest summary: Gaveta makes storing a secret hard and loud, assumes it will sometimes
fail, and ensures that when it does, the secret still cannot leave your machine.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | not found (`show <missing>`) |
| `2` | usage — empty input, reserved word, parse error |
| `3` | **blocked — a secret was detected and not saved** |

A wrapper script can tell "nothing to capture" (`2`) from "that was a secret" (`3`).

See [ADR-003](adr/ADR-003-secret-gate.md) for the reasoning behind the exit code, the
non-tty policy, and the verdict model.
