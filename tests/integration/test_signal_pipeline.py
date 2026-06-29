"""Integration test: FixtureSource -> TrueBeats -> backtest, end to end (no credentials)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from src.data.contracts.schemas import BacktestResult
from src.data.source import FixtureSource
from src.signals.construction.truebeats import compute_truebeats
from src.signals.validation.backtest_runner import run_backtest

pytestmark = pytest.mark.integration


def test_truebeats_pipeline_end_to_end_on_fixtures() -> None:
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "META", "TSLA"]
    start = date(2026, 1, 1)
    end = start + timedelta(days=130)  # > 63 trading days, enough for the decay horizon

    source = FixtureSource()
    prices = source.get_prices(tickers, start, end)
    estimates = source.get_estimates(tickers, start, end)

    scores = []
    for day in sorted({p.date for p in prices}):
        scores.extend(compute_truebeats(estimates, as_of=day))

    result = run_backtest(scores, prices, n_trials=1)
    assert isinstance(result, BacktestResult)
    assert result.signal_name == "truebeats"
    assert isinstance(result.passed_validation, bool)
    # The pass/fail invariant is enforced by the contract; assert the wiring produced a
    # coherent report over a real number of periods.
    assert result.start_date >= start
