"""System test: full pipeline from data pull to portfolio weights (Milestone 5).

Data (fixtures) -> four signals -> de-duplication -> optimal weights -> combined signal ->
mean-CVaR-aware portfolio. Run monthly and before any live session (TESTING.md).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from src.data.contracts.schemas import PortfolioWeights
from src.data.source import FixtureSource
from src.portfolio.constraints import PortfolioConstraints, violations
from src.portfolio.construction import construct_portfolio
from src.signals.combination.optimal_weights import (
    combine_signals,
    optimal_weights,
    signal_ic_series,
)
from src.signals.combination.signal_selector import select_signals
from src.signals.construction.fundamental_factors import compute_fundamental_factors
from src.signals.construction.ownership_signal import compute_ownership_momentum
from src.signals.construction.supply_chain_signal import compute_supply_chain_signal
from src.signals.construction.truebeats import compute_truebeats
from src.signals.validation.ic_calculator import (
    DEFAULT_FORWARD_HORIZON_DAYS,
    compute_forward_returns,
)

pytestmark = pytest.mark.system

_TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "META", "TSLA", "AMD"]


def test_end_to_end_data_to_portfolio_weights() -> None:
    start = date(2026, 1, 1)
    end = start + timedelta(days=160)
    source = FixtureSource()
    prices = source.get_prices(_TICKERS, start, end)
    estimates = source.get_estimates(_TICKERS, start, end)
    fundamentals = source.get_fundamentals(_TICKERS, start - timedelta(days=400), end)
    ownership = source.get_ownership(_TICKERS, start - timedelta(days=200), end)
    links = source.get_supply_chain(_TICKERS)
    dates = sorted({p.date for p in prices})

    signals: dict[str, list] = {
        "truebeats": [],
        "fundamental_factors": [],
        "ownership_momentum": [],
        "supply_chain_contagion": [],
    }
    for day in dates:
        signals["truebeats"] += compute_truebeats(estimates, as_of=day)
        signals["fundamental_factors"] += compute_fundamental_factors(fundamentals, as_of=day)
        signals["ownership_momentum"] += compute_ownership_momentum(ownership, as_of=day)
        signals["supply_chain_contagion"] += compute_supply_chain_signal(links, prices, as_of=day)

    forward_returns = compute_forward_returns(prices, DEFAULT_FORWARD_HORIZON_DAYS)
    ic_series = signal_ic_series(signals, forward_returns)

    selection = select_signals(signals)
    assert selection.kept  # at least one signal survives de-duplication

    kept = {name: signals[name] for name in selection.kept}
    weights = optimal_weights({name: ic_series[name] for name in selection.kept})
    assert sum(abs(w) for w in weights.values()) == pytest.approx(1.0)

    combined = combine_signals(kept, weights)
    assert combined

    as_of = max(s.date for s in combined)
    pw = construct_portfolio(combined, prices, as_of)
    assert isinstance(pw, PortfolioWeights)
    assert violations(pw.weights, PortfolioConstraints()) == []
    assert abs(sum(pw.weights.values())) < 0.05  # ~dollar-neutral
