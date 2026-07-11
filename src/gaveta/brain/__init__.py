"""Local classification — the contextual layer (Stage 4, ADR-004).

`gaveta.brain` turns post-gate text into a `Classification` (type / title / tags /
content). It is the *only* package permitted to import a network client (`httpx`), and
then only to reach a local Ollama — the architecture fence in
`tests/test_architecture.py` enforces both halves of that rule. Everything here runs
after the gate, so it only ever sees cleared or `[REDACTED]` text.

The public surface fills in over the course of the stage: the `Classifier` protocol, the
`HeuristicClassifier` floor, and the `OllamaClassifier` adapter that degrades to it.
"""
