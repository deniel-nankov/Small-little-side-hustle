# Copilot review instructions

This repo is an **institutional trading research platform** (signals → validation →
portfolio → execution). When reviewing a PR, prioritise the checks below and report only
concrete `file:line` issues — no praise, no restating the diff.

## Compliance (highest priority — this is real-money research)
- **Point-in-time only.** Any data used in a backtest must be point-in-time
  (`point_in_time` / `is_point_in_time`). Flag reads of data dated after the as-of date.
- **No look-ahead / outcome leakage.** Forward returns (targets) must never feed signal
  construction. Flag a signal that reads future prices, realized outcomes, or test-set data.
- **Train/test discipline.** Validation/IC must be out-of-sample. Flag fitting and
  evaluating on the same window.
- **Audit logging.** Significant decisions (validation, promotion, portfolio, trades) should
  be recorded via `src/monitoring/audit.py`.
- **Secrets.** No `os.environ`/`os.getenv` outside `config/settings.py`; no hardcoded
  credentials; never log secret values (they are `SecretStr`).

## Architecture / data flow (see docs/ARCHITECTURE.md)
Dependencies point **downward only**:
`src/data` → `src/signals/{construction,discovery}` → `src/signals/validation` →
`src/signals/combination` + `src/portfolio` → `src/execution`.
Nothing imports from `src/monitoring` except to get the logger. Flag any upward import.

## Coding standards (see docs/PRINCIPLES.md)
- Data crossing a module boundary must be a **Pydantic contract** from
  `src/data/contracts/schemas.py` — never a raw dict/DataFrame.
- Use the structured logger (`src/monitoring/logger.get_logger`), never `print`.
- No bare `except:`; no silent failures (raise or return an explicit result).
- Full type hints; `mypy --strict` must pass.
- Every ticket ships a dedicated `tests/unit/test_<name>.py`; the full suite must be green.

## Security
Parameterised SQL only; no `eval`/`exec`/unsafe `pickle`/`yaml.load`; network calls need
timeouts; validate external input at boundaries.
