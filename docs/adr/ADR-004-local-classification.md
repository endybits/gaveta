# ADR-004 — Local classification: a small instruct model over localhost HTTP, with a heuristic floor

- **Status:** Accepted
- **Date:** 2026-07-11
- **Stage:** 4 — Local classification & tagging

## Context

Stage 4 makes a capture describe itself. After the gate clears input, something has to decide
whether the text is a `link`, a `command`, or a `note`, extract a short **title**, propose
**tags**, and pull out the **content** — the clean copyable payload (the bare command, the bare
URL, the bare snippet) with the surrounding narrative stripped off. The design choice is *what*
does the deciding, and how it reaches the model without breaking the promise the whole project is
built on: the drawer never leaves the machine.

Three decisions have to be settled, and each outlives the stage:

1. **Which model, and on what evidence?** The default has to be small enough to run on a
   developer's laptop, good enough at instruction-following to return strict JSON, and comfortable
   with bilingual (English/Spanish) input, because the user's captures mix the two. The number was
   earmarked as far back as Stage 1 and has been renumbered twice on the way here.
2. **How does `gaveta.brain` talk to Ollama?** Ollama is local HTTP on `:11434`, but *the entire
   architecture forbids network imports* — a test fails the build if any module under `src/gaveta`
   imports `httpx`, `socket`, `urllib`, and so on. Ollama is the first thing that legitimately
   needs an HTTP client. The fence has to open exactly wide enough to let one module reach
   localhost, and not one byte wider.
3. **When does classification run, and what happens when the model is slow or absent?** Capture is
   the hot path; it must never feel slow and must never fail because a model is missing. The timing
   and the fallback behavior are a UX contract, not an implementation detail.

The classifier is *core*: `Classifier.classify(text) -> Classification` is a pure seam that knows
nothing of argv or a terminal, the same discipline `gate.scan` follows. It only ever sees
**post-gate text** — cleared or `[REDACTED]` — because the gate runs first, always. The four-layer
defense narrative and the honest-limits framing live in
[`docs/security-model.md`](../security-model.md); this ADR records the three decisions above.

## Decision 1 — The default model is `qwen2.5:3b-instruct`, and swapping is free

**Gaveta defaults to `qwen2.5:3b-instruct` served by Ollama. The choice is recorded here against
explicit selection criteria; the empirical validation against the user's 20 real samples is
*pending*, and the config file (`~/.gaveta/config.toml`) makes changing the model a one-line edit,
so the default is a starting point, not a commitment.**

The selection criteria, in priority order:

| Criterion | Why it matters | `qwen2.5:3b-instruct` |
|---|---|---|
| Strict-JSON adherence | The contract is `{type,title,tags,content}` JSON only; a model that narrates around the JSON forces a fallback every time | Strong instruction-following at its size; pairs with Ollama's `format=json` |
| Bilingual (EN/ES) | Real captures mix English and Spanish mid-sentence | Broad multilingual training, unlike the more English-centric small models |
| Size / latency | Must run on a laptop and answer inside the capture budget | ~2 GB; runs on CPU or a small GPU |
| Availability in Ollama | The default has to `ollama pull` cleanly | First-class Ollama tag |

The alternatives considered: **`gemma2:2b`** is smaller and lower-latency but weaker at strict-JSON
adherence and multilingual nuance — viable if latency ever dominates, and the config makes it a
one-line switch. **`llama3.2:3b`** is comparable in size with decent JSON but is generally reported
weaker than Qwen 2.5 at Spanish; a reasonable second choice.

**On the honesty of this record.** The implementation environment has no Ollama installed and
nothing listening on `:11434` (probed). So this decision states **what was assumed, not what was
measured**: the criteria above are judgments from the models' documented characteristics, *not*
benchmark results on Gaveta's own inputs. No accuracy or latency numbers are quoted, because none
were produced here. The real validation — run the 20 samples, eyeball `type`/`title`/`tags`/
`content` quality, confirm the timing budget holds — is a **manual checklist for the user's
machine**, and until it runs, the default carries exactly that caveat. This is why the config
exists: the moment the samples say a different model is better, changing it costs one line and no
code.

**Prompt revision (post-release).** The first live captures on `qwen2.5:3b-instruct` exposed
prompt weaknesses, not model ones: a command containing a URL was miscalled a `link`, and tags
drifted toward importance/sentiment (`important`, `secret`) instead of subject matter. The prompt
was revised — command beats link when both are present, tags are scoped to technologies/systems/
topics, and the capture is fenced as untrusted data — and shipped as its own change. The pending
20-sample validation therefore applies to the **revised** prompt; the model default is unaffected.

## Decision 2 — `gaveta.brain` reaches Ollama with plain `httpx`, and the fence opens for that module only

**`OllamaClassifier` POSTs to `{endpoint}/api/generate` with plain `httpx` (not the official
`ollama` client). The architecture test is amended so that `httpx` is importable *only* by files
under `src/gaveta/brain/`; every other module keeps the full network-import ban, `httpx` included.
A second test asserts that `brain` contains no non-localhost URL literal, and the endpoint is
validated as localhost at construction in code. The fence gets more precise, not weaker.**

**Why `httpx` over the official client.** The `ollama` package pulls `httpx` transitively anyway,
so it is not lighter; it wraps its own HTTP, so the fence would have to whitelist the whole package
rather than one well-understood dependency; its timeout control is coarser than a per-request
`httpx` timeout; and mocking it means patching a client object, where a plain `httpx` call behind a
small `_post` seam is monkeypatched exactly the way the rest of this codebase already fakes seams
(`_prompt_choice`, `FakeVaultProvider`). One dependency, full control of the strict-JSON request,
a hard per-request timeout, and a clean mock.

**Why the fence opens for `brain` only.** The containment property (layer 4) is *"nothing under
`src/gaveta` imports a network library"* — a single `_NETWORK_MODULES` set intersected against
every file's imports. Ollama breaks that for exactly one module. Rather than delete `httpx` from
the ban list globally (which would let *any* future module phone home unnoticed), the amendment
scopes the exception: for files whose path is under `brain/`, the ban set is
`_NETWORK_MODULES - {"httpx"}`; for every other file it is the full set. So a stray `import httpx`
in `core.py` or `cli.py` still fails the build.

Import-name scoping is necessary but not sufficient — the AST sees `import httpx`, not the URL it
dials. So a companion test walks `brain` for string literals and fails on any URL that is not
`localhost`, `127.0.0.1`, or `::1`, and the `OllamaConfig` validates its endpoint as localhost at
construction (a non-local endpoint is a configuration error, not a silent exfiltration path). The
two together mean: only `brain` may hold an HTTP client, and that client may only ever dial the
local machine.

## Decision 3 — Classification is synchronous with a hard 2.5s budget; a miss falls back to heuristics

**Classification runs synchronously inside `capture`, on the post-gate text, with a hard total
timeout of 2.5 seconds. If Ollama is absent, refuses the connection, times out, returns non-200,
or returns malformed/partial JSON, `OllamaClassifier` delegates to `HeuristicClassifier` and the
capture is saved anyway. Capture never blocks on a model and never fails because of one.
`gaveta retag <id>` re-runs classification later — the upgrade path for anything saved via the
fallback.**

**Why synchronous, not background.** A background classifier means a capture that is `unknown` for
a second and then mutates under the user, an extra process or thread to manage, and a race against
`show`. Synchronous keeps the model a pure function in the pipeline and the `✓ saved` line
truthful the instant it prints. The cost is latency on the capture path, which the budget bounds.

**Why 2.5 seconds.** It is the ceiling on how slow capture may feel — enough for a warm small model
to answer (`~0.5s` connect + `~2.0s` read), short enough that the miss path still returns
promptly. A cold or loaded model that blows the budget is not an error; it is a fallback. The
number lives in config, so a user with a faster machine can tighten it or a slower one loosen it.

**What the user sees on each path.** On a hit, the `✓ saved` line carries the real classification:
`✓ saved · id 7 · command · ssh, rds, qa`. On a miss (no Ollama, timeout, bad JSON), the same line
carries the *heuristic* verdict — a lone URL becomes `link` with the URL as content, shell-ish text
becomes `command`, everything else becomes `note` with null content — and no error is printed,
because a fallback is not a failure. Running `gaveta retag 7` after the model is available upgrades
the item in place and prints `✓ retagged · id 7 · …`.

**Config errors are usage errors, not a new exit code.** A malformed `config.toml`, or an endpoint
that is not localhost, is refused with a clear message at exit `2` (USAGE) — the same class as a
bad argument or an unknown `ls` type. It is a "your config is wrong" failure the user fixes by
editing the file; it does not warrant a fifth exit code, and folding it into the existing usage
code keeps the [exit-code table](../security-model.md#exit-codes) at four entries. A missing config
file is not an error at all — it means defaults.

## Consequences

**We accept** a model whose fitness for Gaveta's own inputs is *asserted, not yet measured*. The
default rests on documented model characteristics and a config that makes it trivial to change; the
real judgment waits on the manual validation against 20 samples. This ADR is honest about that gap
rather than papering over it with borrowed benchmarks.

**We accept** the first crack in the network fence. `httpx` is no longer universally banned — but
it is banned everywhere except `brain`, the localhost-only guarantee is tested from two directions
(import scope and URL literals), and the endpoint is validated in code. The fence is more precise
than before, and a module that tries to reach past localhost still fails the build.

**We gain** a capture that never blocks or fails on the model. Ollama is strictly optional: absent,
slow, or broken, the heuristic floor catches every capture, and `retag` is the upgrade path. The
zero-friction promise survives a missing dependency.

**We gain** a classifier that is pure core. `classify(text) -> Classification` knows nothing of a
terminal or an exit code, so the daemon (Stage 7) and the MCP server (Stage 9) inherit it without a
rewrite — and because it runs *after* the gate, it only ever sees post-gate text, a property the
pipeline-order test asserts on the redact path (the model is handed `[REDACTED]`, never the secret).

**We give up** background classification and its complexity, deliberately. The capture path pays up
to 2.5s of latency on a model hit, bounded by config, in exchange for a `✓ saved` line that is true
the moment it prints and a pipeline with no races.

## Revisiting this

Revisit the default model the moment the 20-sample validation says another model classifies better
or extracts cleaner content — that is what the config is for, and changing it is a one-line edit,
not an ADR. Revisit the *criteria* only if the input distribution changes shape (a new language, a
new item type).

Revisit the transport only on a move that makes the official client materially better — richer
streaming, a feature `httpx` cannot express cleanly — and even then keep the fence scoped to
`brain` and the localhost guarantee tested. The exception never widens past one module.

Revisit the timing budget if the manual validation shows 2.5s is routinely too tight on the user's
hardware (raise it in config) or the fallback fires so often that synchronous classification stops
earning its latency (then, and only then, reconsider a background path). The fallback-never-fails
invariant does not move.
