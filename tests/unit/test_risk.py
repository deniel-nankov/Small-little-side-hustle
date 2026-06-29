"""Unit tests for portfolio risk statistics."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from src.portfolio.risk import (
    build_scenarios,
    conditional_value_at_risk,
    portfolio_scenario_returns,
    value_at_risk,
)

from tests.synth import flat_bar


def test_cvar_is_mean_of_worst_tail() -> None:
    returns = [-0.10, -0.05, -0.02, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
    # beta=0.8 -> worst 20% = 2 observations: -0.10 and -0.05 -> CVaR = 0.075
    assert conditional_value_at_risk(returns, beta=0.8) == pytest.approx(0.075)


def test_var_is_quantile_loss() -> None:
    returns = [-0.10, -0.05, -0.02, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
    assert value_at_risk(returns, beta=0.8) == pytest.approx(0.05)


def test_cvar_and_var_empty_is_zero() -> None:
    assert conditional_value_at_risk([]) == 0.0
    assert value_at_risk([]) == 0.0


def test_portfolio_scenario_returns() -> None:
    weights = {"A": 0.5, "B": -0.5}
    scenarios = [{"A": 0.10, "B": 0.00}, {"A": 0.00, "B": 0.10}]
    assert portfolio_scenario_returns(weights, scenarios) == pytest.approx([0.05, -0.05])


def test_build_scenarios_returns_recent_cross_sections() -> None:
    d0 = date(2026, 1, 5)
    bars = []
    for i, close in enumerate([100.0, 110.0, 121.0]):
        bars.append(flat_bar("AAA", d0 + timedelta(days=i), close))
    scenarios = build_scenarios(bars, as_of=d0 + timedelta(days=2), lookback_days=5)
    assert len(scenarios) == 2  # two return observations from three prices
    assert scenarios[0]["AAA"] == pytest.approx(0.10)
