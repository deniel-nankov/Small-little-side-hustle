# yale-alpha-fund

An institutional-grade **alpha discovery and trading research platform** for the Yale
hedge fund club. The system pulls institutional financial data, runs it through
signal-discovery and hand-built signal modules, validates every signal rigorously,
combines survivors into a portfolio, and routes execution through QuantConnect →
Interactive Brokers — with monitoring and tests at every layer.

> **Status:** Milestone 1 (Foundation). Scaffolding, documentation, data contracts,
> config, logging, and the `DataSource` abstraction are in place. No live trading.
> No real FactSet pull yet. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## The six layers

| Layer | What it does | Code |
|------|---------------|------|
| 1. Ingestion | FactSet → validated DataFrames / Pydantic contracts | `src/data/` |
| 2. Discovery | AI agents propose candidate signal formulas | `src/signals/discovery/` |
| 3. Construction | Hand-built signals (TrueBeats, ownership, supply chain…) | `src/signals/construction/` |
| 4. Validation | IC, decay, regime, p-value guard, backtest | `src/signals/validation/` |
| 5. Combination | De-dup + optimal weights + mean-CVaR portfolio | `src/signals/combination/`, `src/portfolio/` |
| 6. Execution | QuantConnect → paper → live (IBKR) | `src/execution/` |

Monitoring (`src/monitoring/`) is a horizontal concern — it can see everything;
nothing depends on it.

## Quick start

```bash
git clone <repo> && cd yale-alpha-fund
make venv && source .venv/bin/activate
make install
cp .env.example .env          # then fill in real credentials (never commit .env)
make test-unit                # foundation tests must pass
```

By default the platform runs against the **fixture** data source (deterministic
synthetic data) so the whole pipeline is buildable and testable with no API access.
Set `DATA_SOURCE=factset` in `.env` once FactSet API credentials are entitled.

## Read these before contributing

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the system fits together
- [docs/PRINCIPLES.md](docs/PRINCIPLES.md) — the 12 coding rules (non-negotiable)
- [docs/DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md) — the Pydantic schemas that cross module boundaries
- [docs/TESTING.md](docs/TESTING.md) — three test levels + the 7 signal-validation tests
- [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) — how to add a signal safely

## Honest scope notes

Some components named in the design brief are **real installable tools** (NVIDIA NeMo
Agent Toolkit, NVIDIA cuOpt, QuantConnect LEAN, Interactive Brokers API). Others are
**methodologies we implement ourselves** — there is no SDK to `pip install` for
"QuantaAlpha", "MadEvolve", "Beyond Prompting", or FactSet's "Signal Selector /
Optimal Weights" (the latter is a Workstation feature, not an API). Those modules are
clean interfaces plus our own implementations. "TrueBeats" is a FactSet product; our
`truebeats.py` re-implements the published Vinesh Jha methodology from FactSet's blog.
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#component-reality-check).

## Safety

This repository can route real-money orders. **Nothing trades live without** passing
the full pre-flight checklist in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): ≥3 signals
in PRODUCTION, ≥30 days of paper trading with positive IC, and a human sign-off.
Start with the smallest IBKR order size for the first 60 days.
