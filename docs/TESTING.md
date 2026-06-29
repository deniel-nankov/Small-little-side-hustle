# Testing

We test at three levels. All three must pass before code is "done". Separately, every
signal must clear a 7-test validation suite before it can go live.

## Level 1 — Unit tests (`tests/unit/`)

Test individual functions in complete isolation. Mock every external dependency (FactSet
API, database, filesystem); for data, use `FixtureSource`. Aim for 100% coverage of
`src/signals/` and `src/data/contracts/`.

Rules:
- Each test asserts exactly one thing.
- Naming: `test_<function>_<scenario>_<expected_result>`,
  e.g. `test_ic_calculator_with_zero_variance_raises_error`.
- No test takes more than ~2 seconds. **No unit test makes a network call.**

Run: `make test-unit` (includes the coverage gate).

## Level 2 — Integration tests (`tests/integration/`)

Test that modules work together. These **may** make real API calls (use a sandbox or test
account) and are run before merging, not on every commit.

Rules:
- Use real but small data (e.g. 10 stocks, 30 days).
- Validate that data returned from FactSet matches the expected schema.
- Tests that need credentials **skip themselves** when credentials are absent, so CI stays
  green without secrets.

Run: `make test-integration`.

## Level 3 — System tests (`tests/system/`)

Full end-to-end: data pull → signal score → portfolio weights. Run **monthly** and before
any live trading session.

## Markers

`pytest` markers (declared in `pyproject.toml`): `unit`, `integration`, `system`. Select
with `pytest -m integration`, etc.

## Signal-specific validation (the 7 tests)

These live in `src/signals/validation/`, **not** in `tests/`. Every signal must pass
**all 7** before entering the live registry. Thresholds are named constants (Rule 1).

| # | Test | Pass criterion |
|--:|------|----------------|
| 1 | **IC** | Mean IC > 0.015 on out-of-sample data (not seen during development) |
| 2 | **ICIR** | IC / std(IC) > 0.5 (stable, not occasionally lucky) |
| 3 | **P-value guard** | Actual IC significantly above the expected max IC from N random trials (MadEvolve method) — guards against multiple-testing luck |
| 4 | **Decay** | IC > 0.01 at a 3-month forward horizon (longevity) |
| 5 | **Regime** | Positive IC in ≥ 3 of 4 regimes (bull, bear, high-vol, low-vol) |
| 6 | **Correlation** | Spearman corr < 0.5 with every existing registry signal (adds new info) |
| 7 | **Sector neutrality** | IC holds after removing sector effects (not just a sector bet) |

A signal that fails any test goes back to development, not into production. The outcome is
recorded as a `BacktestResult` (`passed_validation` + `failure_reasons`).

## Current status (Milestone 1)

`make test-unit` → 35 passed, 4 skipped (placeholders for unbuilt modules). The skips are
deliberate reminders that those modules are unfinished — see the blocker protocol in the
project brief. mypy (strict) and ruff both pass clean.
