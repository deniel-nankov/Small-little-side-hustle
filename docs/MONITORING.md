# Monitoring

Monitoring is a horizontal concern: it observes every layer, and **nothing depends on it**
(ARCHITECTURE.md). Code lives in `src/monitoring/`.

## What gets monitored

| Cadence | Metric | Alert condition |
|---------|--------|-----------------|
| Daily   | IC of every `PRODUCTION` signal | any drops below 0.01 |
| Daily   | Portfolio P&L vs. expected return | drawdown exceeds 3% |
| Daily   | Data pipeline success/failure | FactSet pull fails |
| Weekly  | Regime detection output | (informational: which regime are we in?) |
| Monthly | Full signal-decay analysis (all production signals) | decay below threshold |
| Monthly | Correlation matrix of production signals | any pair exceeds 0.7 |

## Alert channels

- **Critical** (data pipeline down, trading error): Slack **and** email, immediately.
- **Signal IC degradation:** Slack daily digest.
- **Everything else:** stored in the database, viewable in a notebook dashboard.

Alerts are sent via `src/monitoring/alerts.py`. Slack requires `SLACK_WEBHOOK_URL`; when it
is absent, alerting degrades gracefully (logs a warning) rather than crashing.

## Logging standard

Use `get_logger(__name__)` from
[`src/monitoring/logger.py`](../src/monitoring/logger.py) everywhere — never `print` or the
stdlib `logging` module (PRINCIPLES.md Rule 9). Logging is structured (`structlog`):

- **Development:** human-readable, colored console output.
- **Production:** single-line JSON (one object per event), selected by `APP_ENV`.

Every event includes a timestamp (ISO-8601 UTC), level, logger (module) name, and a short
`event` key, plus any structured key/values you pass. The `@log_function_call` decorator
emits `call.start` / `call.end` (with elapsed ms) at DEBUG and `call.error` at ERROR — and
always re-raises (no silent failures).

Level semantics: `DEBUG` internal calculations · `INFO` major steps · `WARNING`
unexpected-but-recoverable · `ERROR` failed, needs attention · `CRITICAL` cannot continue.

The canonical declarative reference is
[`config/logging_config.yaml`](../config/logging_config.yaml); `logger.py` is kept in sync
with it.

## Never log

API keys, tokens, secrets, passwords (the `SecretStr` type prevents this), or raw dumps of
licensed FactSet data. See [SECURITY.md](SECURITY.md).
