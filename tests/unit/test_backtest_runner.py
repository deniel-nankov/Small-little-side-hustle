"""Unit tests for the backtest runner (the 7-test validation orchestrator)."""

from __future__ import annotations

import random
from datetime import date

import pytest
from src.data.contracts.schemas import BacktestResult, SignalScore
from src.signals.validation.backtest_runner import run_backtest

from tests.synth import business_days, flat_bar, make_noise_scores, make_predictive_universe


def test_predictive_signal_passes_all_tests() -> None:
    scores, prices = make_predictive_universe()
    result = run_backtest(scores, prices, n_trials=1)
    assert isinstance(result, BacktestResult)
    assert result.passed_validation is True
    assert result.failure_reasons == []
    assert result.mean_ic > 0.5
    assert result.annualized_return > 0
    assert result.max_drawdown <= 0
    assert result.regime_results  # non-empty


def test_noise_signal_fails_with_reasons() -> None:
    _, prices = make_predictive_universe()
    noise = make_noise_scores(prices)
    result = run_backtest(noise, prices, n_trials=1)
    assert result.passed_validation is False
    assert any("#1" in reason for reason in result.failure_reasons)


def test_correlation_test_flags_duplicate_signal() -> None:
    scores, prices = make_predictive_universe()
    result = run_backtest(scores, prices, n_trials=1, existing_signals={"dup": scores})
    assert result.passed_validation is False
    assert any("#6" in reason for reason in result.failure_reasons)


def test_stock_selective_signal_survives_single_sector() -> None:
    # Subtracting a constant sector mean preserves the within-sector ranking, so a genuine
    # stock-selective signal is unharmed by neutralization.
    scores, prices = make_predictive_universe()
    sectors = {f"T{i:02d}": "TECH" for i in range(12)}
    assert run_backtest(scores, prices, n_trials=1, sectors=sectors).passed_validation is True


def test_pure_sector_bet_fails_sector_neutrality() -> None:
    days = business_days(date(2026, 1, 1), 170)
    tickers = [f"T{i:02d}" for i in range(12)]
    sector = {t: ("A" if i < 6 else "B") for i, t in enumerate(tickers)}
    prices = []
    for t in tickers:
        rng = random.Random(f"sec|{t}")
        price = 100.0
        drift = 0.003 if sector[t] == "A" else -0.003  # identical within each sector
        for k, day in enumerate(days):
            if k > 0:
                price = max(price * (1 + drift + rng.gauss(0.0, 0.01)), 1.0)
            prices.append(flat_bar(t, day, price))
    scores = [
        SignalScore(
            ticker=t,
            date=day,
            signal_name="sectorbet",
            signal_version="1.0.0",
            raw_score=(10.0 if sector[t] == "A" else 0.0) + 0.001 * i,
            rank_score=0.5,
            data_inputs=["x"],
        )
        for day in days
        for i, t in enumerate(tickers)
    ]
    result = run_backtest(scores, prices, n_trials=1, sectors=sector)
    assert result.passed_validation is False
    assert any("#7" in reason for reason in result.failure_reasons)


def test_empty_scores_raises() -> None:
    _, prices = make_predictive_universe()
    with pytest.raises(ValueError, match="no scores"):
        run_backtest([], prices)
