# Data contracts

## What is a data contract?

A data contract is a Pydantic model that defines exactly what data looks like when it
crosses from one module to another. It is **enforced at runtime**. If a module returns data
that does not match the contract, the system raises immediately rather than passing bad
data downstream (PRINCIPLES.md Rule 12).

All contracts live in [`src/data/contracts/schemas.py`](../src/data/contracts/schemas.py)
and share a strict base configuration:

- `frozen=True` — immutable (the Golden Rule: no shared mutable state).
- `extra="forbid"` — unknown fields are an error (fail fast on schema drift).
- `str_strip_whitespace=True` — incidental whitespace never corrupts a key.

> **Rule:** Any function that takes or returns financial data uses these types in its
> signature. No raw dicts or DataFrames cross a module boundary without first being
> validated through a schema.

## Enumerations

- `DataSourceName` — `factset` | `backup` | `fixture`. (`fixture` = synthetic test data,
  never production.)
- `Metric` — `EPS` | `Revenue` | `EBITDA` | `EBIT` | `NetIncome` | `FCF`.
- `SignalStatus` — `DISCOVERED` | `VALIDATED` | `STAGING` | `PRODUCTION` | `RETIRED`
  (see [SIGNAL_REGISTRY.md](SIGNAL_REGISTRY.md)).

## Core contracts

### `PriceData`
One ticker's OHLCV bar for one date.
Fields: `ticker`, `date`, `open`, `high`, `low`, `close`, `volume`, `adjusted_close`,
`data_source` (`DataSourceName`), `point_in_time` (bool — `True` = safe for backtesting).
Validation: prices > 0, volume ≥ 0, ticker upper-cased, and **OHLC consistency**
(`low ≤ open,close ≤ high`).

### `EstimateData`
One analyst's estimate of one metric for one fiscal period.
Fields: `ticker`, `analyst_id`, `broker`, `estimate_date` (when the estimate was made),
`fiscal_year`, `fiscal_quarter` (1–4), `metric` (`Metric`), `value`, `currency` (ISO-3),
`is_point_in_time` (must be `True` for backtest use), and optional `analyst_accuracy`
(0–1, this analyst's historical accuracy on this metric — used by TrueBeats).

### `SignalScore`
A signal's output for one ticker on one date.
Fields: `ticker`, `date`, `signal_name`, `signal_version` (semver, validated),
`raw_score`, `rank_score` (cross-sectional rank 0–1), `ic_trailing_90d` (optional, for
monitoring), `data_inputs` (which data fields fed the signal — required, non-empty).

### `BacktestResult`
The outcome of validating one signal over a date range.
Fields: `signal_name`, `start_date`, `end_date`, `mean_ic`, `ic_std` (≥0), `icir`,
`t_statistic`, `p_value` (0–1), `positive_ic_ratio` (0–1), `annualized_return`,
`max_drawdown` (≤0), `sharpe_ratio`, `regime_results` (regime→IC), `passed_validation`,
`failure_reasons`.
Validation: `end_date ≥ start_date`; a passing result has **no** failure reasons; a failing
result has **at least one** (you can never silently "fail without a reason").

### `PortfolioWeights`
Target weights for one rebalance date.
Fields: `date`, `weights` (ticker→weight, each in **[-1, 1]**), `expected_return`,
`expected_cvar`, `turnover` (≥0), `construction_method`.

## Changing a contract

A schema change is a breaking change. It requires:
1. A PR labeled `data-contract`.
2. Updating every producer and consumer of the contract in the same PR.
3. Updating this document.
4. Bumping affected signal versions if the change alters their inputs/outputs.
