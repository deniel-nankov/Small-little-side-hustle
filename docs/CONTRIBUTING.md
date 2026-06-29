# Contributing

How to add new components safely. Read [PRINCIPLES.md](PRINCIPLES.md) first.

## General workflow

1. Open a GitHub Issue from the right template; apply labels (see below).
2. Branch from `main`. Naming: `signal/<name>`, `feat/<short>`, `fix/<short>`,
   `data/<short>`, `docs/<short>`.
3. Build the smallest reviewable change. Follow the principles.
4. Write tests. Run `make lint && make test-unit` locally until green.
5. Open a PR using the template. CI must pass; ≥1 review required.
6. Squash-merge with a `[type]: description` message.

## How to add a new signal

1. **Issue** — use the `new_signal` template: hypothesis, economic intuition, data sources,
   expected holding period, category, and point-in-time confirmation.
2. **Branch** — `signal/<signal_name>`.
3. **Build** — implement in `src/signals/construction/<signal_name>.py`. It consumes data
   via a `DataSource` and returns `SignalScore` objects. No look-ahead.
4. **Unit tests** — `tests/unit/test_<signal_name>.py`. Use `FixtureSource`; test the math
   against known ground truth.
5. **Validate** — run the 7-test suite via `src/signals/validation/backtest_runner.py`.
   It produces a `BacktestResult`.
6. **Register** — if it passes, add it to the signal registry with status `VALIDATED`
   (point-in-time = confirmed, data sources listed).
7. **PR** — open it; another member reviews; CI (incl. `signal_validation.yml`) must pass.
8. **Stage** — on merge, the signal enters `STAGING` for 30 days of paper trading.
9. **Promote** — after 30 days with live IC above threshold, promote to `PRODUCTION`.

## How to retire a signal

Open an Issue labeled `signal-retirement` documenting the IC-decay evidence. Remove it from
the portfolio weights, set the registry status to `RETIRED`. **Keep all code** — never
delete it.

## Labels

**Signal:** `signal`, `signal-retirement`, `signal-validated`, `signal-failed`.
**Data:** `data`, `data-contract`.
**Engineering:** `bug`, `feat`, `refactor`, `test`, `docs`, `infra`, `security`.
**Priority:** `P0-critical`, `P1-high`, `P2-medium`, `P3-low`. (`blocked` for items waiting
on an external dependency.)

## Project board

Kanban columns: `BACKLOG → SPRINT → IN PROGRESS → IN REVIEW → TESTING → DONE`. Every issue
sits in a column; items in `DONE` have a linked merged PR.

## When you hit a blocker

If a module can't be finished due to a dependency (missing API access, unclear data format):

1. Open an Issue labeled `P1-high` + `blocked`.
2. Write a stub that raises `NotImplementedError("Blocked: <reason>")`.
3. Write the test anyway — it stays skipped/failing as the reminder it's unfinished.
4. Move on; return when unblocked. **Never skip writing the test.**
