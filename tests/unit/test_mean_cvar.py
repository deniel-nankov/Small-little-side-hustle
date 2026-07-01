"""Unit tests for the exact mean-CVaR LP solver (ticket #11, Stage 5)."""

from __future__ import annotations

import pytest
from src.portfolio import risk
from src.portfolio.construction import construct_portfolio
from src.portfolio.mean_cvar import solve_mean_cvar

from tests.synth import make_predictive_universe

_LOOKBACK = 63


def _scenarios_and_mu() -> tuple[dict[str, float], list[dict[str, float]]]:
    _, prices = make_predictive_universe()
    as_of = max(p.date for p in prices)
    scenarios = risk.build_scenarios(prices, as_of, _LOOKBACK)
    tickers = sorted({p.ticker for p in prices})
    mu: dict[str, float] = {}
    for ticker in tickers:
        vals = [sc[ticker] for sc in scenarios if ticker in sc]
        mu[ticker] = sum(vals) / len(vals) if vals else 0.0
    return mu, scenarios


def test_solution_respects_constraints() -> None:
    mu, scenarios = _scenarios_and_mu()
    weights = solve_mean_cvar(mu, scenarios, max_position=0.1, max_gross=1.0)
    assert all(-0.1 - 1e-6 <= w <= 0.1 + 1e-6 for w in weights.values())
    assert sum(abs(w) for w in weights.values()) <= 1.0 + 1e-6
    assert abs(sum(weights.values())) < 1e-6  # exactly dollar-neutral


def test_higher_risk_aversion_raises_expected_return() -> None:
    mu, scenarios = _scenarios_and_mu()
    w_low = solve_mean_cvar(mu, scenarios, max_position=0.1, max_gross=1.0, risk_aversion=0.0)
    w_high = solve_mean_cvar(mu, scenarios, max_position=0.1, max_gross=1.0, risk_aversion=50.0)
    er_low = sum(mu[t] * w_low[t] for t in mu)
    er_high = sum(mu[t] * w_high[t] for t in mu)
    assert er_high >= er_low - 1e-9


def test_lp_cvar_is_not_worse_than_heuristic() -> None:
    # The exact min-CVaR LP must achieve CVaR <= any feasible heuristic on the same set.
    scores, prices = make_predictive_universe()
    as_of = max(p.date for p in prices)
    scenarios = risk.build_scenarios(prices, as_of, _LOOKBACK)
    mu, _ = _scenarios_and_mu()

    w_lp = solve_mean_cvar(mu, scenarios, max_position=0.1, max_gross=1.0, risk_aversion=0.0)
    lp_cvar = risk.conditional_value_at_risk(risk.portfolio_scenario_returns(w_lp, scenarios))

    heuristic = construct_portfolio(scores, prices, as_of)
    heuristic_cvar = risk.conditional_value_at_risk(
        risk.portfolio_scenario_returns(heuristic.weights, scenarios)
    )
    assert lp_cvar <= heuristic_cvar + 1e-4


def test_no_scenarios_raises() -> None:
    with pytest.raises(ValueError, match="scenario"):
        solve_mean_cvar({"A": 0.1}, [], max_position=0.1, max_gross=1.0)


def test_empty_universe_returns_empty() -> None:
    assert solve_mean_cvar({}, [{"A": 0.01}], max_position=0.1, max_gross=1.0) == {}
