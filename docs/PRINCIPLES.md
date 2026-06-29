# Principles

A strict rulebook. Every rule is followed without exception. A PR that violates any of
these is rejected. These rules **override** personal preference.

### Rule 1 — No magic numbers
Every constant has a name. No raw numbers in logic.
Wrong: `if ic > 0.02`. Right: `if ic > IC_ACCEPTANCE_THRESHOLD`.
Thresholds for the 7-test validation suite live in one place and are imported, never
inlined.

### Rule 2 — No silent failures
Every function that can fail either raises an exception or returns an explicit result
type. No `except: pass`. No returning `None` without a documented reason. Errors are
typed, descriptive, and propagate.

### Rule 3 — Every function has a docstring
Format: a one-line summary, then `Args:`, `Returns:`, and `Raises:` sections. If a
function is too complex to explain simply, split it. (Enforced by `ruff` pydocstyle.)

### Rule 4 — No hardcoded credentials
Zero tolerance — one violation rejects the PR. All secrets come from environment variables
loaded through `config/settings.py`. **No module reads `os.environ` directly.** Secrets are
`SecretStr` so they cannot be logged. See [SECURITY.md](SECURITY.md).

### Rule 5 — Type hints everywhere
Every parameter and return value has a type hint. Use Pydantic models for anything crossing
a module boundary — never a raw `dict` or `DataFrame`. (Enforced by `mypy --strict`.)

### Rule 6 — Tests before merge
No code merges to `main` without passing unit tests. New signals additionally require
passing the validation suite (IC > threshold, p-value guard, regime stability). See
[TESTING.md](TESTING.md).

### Rule 7 — One responsibility per module
A module that does two things is two modules. If the module description needs an "and",
split it.

### Rule 8 — Point-in-time data only
Any data used in a backtest must be point-in-time (`point_in_time=True` /
`is_point_in_time=True`). Before using any FactSet field in a backtest, verify it comes
from the Point-in-Time database, and document it in the signal's registry entry. No
outcome leakage, ever.

### Rule 9 — Log everything at the right level
`DEBUG`: internal calculations, function entry/exit. `INFO`: major steps completing.
`WARNING`: unexpected but recoverable. `ERROR`: something failed and needs attention.
`CRITICAL`: the system cannot continue. Use `get_logger()` from `src/monitoring/logger.py`;
never `print` or the stdlib `logging` module directly.

### Rule 10 — Small commits, descriptive messages
Format: `[type]: short description`. Types: `feat`, `fix`, `test`, `docs`, `refactor`,
`chore`. Example: `feat: add FactSet estimates client with retry logic`.

### Rule 11 — No notebook code in production
Notebooks (`notebooks/`) are for research and exploration only. Once a signal is validated
in a notebook, it is rewritten as a proper module in `src/signals/construction/` with full
tests before it can be used anywhere downstream.

### Rule 12 — Fail fast on bad data
Validate all incoming data at module boundaries with Pydantic schemas. Raise a clear,
descriptive error immediately if data does not match the contract. Never propagate
corrupted data silently downstream.

---

### How these are enforced

| Rule | Enforcement |
|------|-------------|
| 3, 5 | `ruff` (pydocstyle `D`) + `mypy --strict` in CI |
| 4 | `make check-secrets` pre-commit + CI grep for `.env` / secret patterns |
| 6 | `pytest tests/unit` + coverage gate in CI; branch protection on `main` |
| 8 | `point_in_time` fields on every data contract; registry entry required |
| 9 | structured logging via `src/monitoring/logger.py` |
| 1, 2, 7, 10, 11, 12 | code review against this checklist (see PR template) |
