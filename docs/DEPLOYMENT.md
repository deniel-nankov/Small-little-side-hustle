# Deployment

How to run this locally and in production.

## Prerequisites

- Python ≥ 3.11
- PostgreSQL (local install or Docker) — only needed once the signal registry is in use
- Credentials for whichever services a given milestone touches (see `.env.example`)

## Local setup

```bash
git clone <repo> && cd yale-alpha-fund
make venv && source .venv/bin/activate
make install                  # runtime + dev deps
cp .env.example .env          # fill in real values; NEVER commit .env
make test-unit                # foundation tests must pass
make lint                     # ruff + mypy
```

By default the platform runs against the **fixture** data source (`DATA_SOURCE=fixture`),
so the whole pipeline is buildable and testable with **no API credentials**. Switch to
`DATA_SOURCE=factset` once FactSet API access is entitled.

### Dependency strategy

The foundation install is intentionally small (`pydantic`, `pydantic-settings`,
`structlog`, `numpy`, `pandas`, `scipy`). Heavier API/client SDKs (FactSet, IBKR,
QuantConnect, NVIDIA, OpenAI, Anthropic, Google, `psycopg`) are added to
`requirements.txt` in the milestone that first uses them. All versions are pinned.

## Configuration profiles

`config/settings.py` selects behaviour from the environment:

- `APP_ENV=development` → human-readable logs; `production` → JSON logs and the **full
  credential set is required** at startup (`Settings.validate_for_runtime()` fails loudly
  if anything is missing).
- `DATA_SOURCE=fixture|factset` → which `DataSource` implementation `get_data_source()`
  returns.

Entry points call `settings.validate_for_runtime()` on startup so misconfiguration fails
immediately rather than mid-run.

## Production

- Inject secrets as OS environment variables or via a secrets manager — do **not** deploy a
  `.env` file (SECURITY.md).
- Run the daily pipeline (`scripts/daily_run.py`, `make run-daily`) on a scheduler; the
  GitHub Actions `daily_pipeline.yml` workflow is the reference schedule (07:00 UTC).
- Ship structured JSON logs to your log aggregator.

## Pre-flight checklist before any real money

**Nothing trades live until every box is checked** (this mirrors the project brief's final
checklist):

- [ ] `pytest tests/unit/` → 0 failures
- [ ] Integration tests pass with real FactSet data
- [ ] System test passes end-to-end
- [ ] ≥ 3 signals in `PRODUCTION` status
- [ ] ≥ 30 days of paper trading with positive IC on all 3 signals
- [ ] Daily monitoring pipeline ran 30+ consecutive days without failure
- [ ] All API credentials rotated in the last 30 days
- [ ] No `P0` or `P1` bugs open
- [ ] Manual review of portfolio weights for reasonableness
- [ ] A human understands every signal in the portfolio
- [ ] Max position size per stock set and verified in `constraints.py`
- [ ] Stop-loss rules defined and implemented in `risk.py`
- [ ] Test alert confirmed delivered (Slack)
- [ ] IBKR **paper** trading confirmed before switching to live

**Then start small** — the smallest IBKR order size for the first 60 days. Verify, then
scale.
