# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Until `v1.0.0` the minor version tracks the stage number from
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).

## [Unreleased]

### Added

- Project scaffolding: `pyproject.toml` (hatchling build, `gaveta-cli` distribution,
  `gaveta` console script) and the `src/gaveta/` package layout.
- `uv` as the environment manager, with `uv.lock` committed for reproducible installs.
  The `pip install -e ".[dev]"` path remains supported.
- Tooling: `ruff` (lint + format), `mypy --strict` on `src/`, `pytest` with coverage,
  and `pre-commit` hooks including a `commit-msg` hook enforcing Conventional Commits.
- CI (GitHub Actions): lint, typecheck, and a `pytest` matrix on Python 3.11/3.12/3.13,
  running in parallel on every push to `main` and every pull request.
- Smoke tests covering package import, the console-script entry point, and that
  `__version__` matches the installed distribution metadata.
- `CONTRIBUTING.md` and this changelog.

### Changed

- The default branch is now `main` (previously `master`).
- Coverage policy is now machine-enforced: `fail_under` in `pyproject.toml` is a ratchet
  that may only be raised at a stage close-out, never lowered. It starts at `90`.
- The version is read from installed distribution metadata rather than duplicated as a
  literal, so `pyproject.toml` is the single source of truth.

[Unreleased]: https://github.com/endybits/gaveta/commits/main/
