"""Unit tests for portfolio construction."""

from __future__ import annotations

import math
from datetime import date

import pytest
from src.data.contracts.schemas import PortfolioWeights
from src.portfolio.constraints import PortfolioConstraints, violations
from src.portfolio.construction import (
    CONSTRUCTION_METHOD,
    CVAR_CONSTRUCTION_METHOD,
    construct_portfolio,
    construct_portfolio_cvar,
)

from tests.synth import make_predictive_universe


def test_construct_portfolio_respects_constraints() -> None:
    scores, prices = make_predictive_universe()
    as_of = max(s.date for s in scores)
    pw = construct_portfolio(scores, prices, as_of)
    assert isinstance(pw, PortfolioWeights)
    assert violations(pw.weights, PortfolioConstraints()) == []
    assert all(-1.0 <= w <= 1.0 for w in pw.weights.values())
    # CVaR may be negative when even the worst-tail scenarios are gains (a strong book).
    assert math.isfinite(pw.expected_cvar)
    assert pw.construction_method == CONSTRUCTION_METHOD


def test_construct_portfolio_respects_tighter_position_cap() -> None:
    scores, prices = make_predictive_universe()
    as_of = max(s.date for s in scores)
    pw = construct_portfolio(
        scores, prices, as_of, constraints=PortfolioConstraints(max_position=0.05)
    )
    assert all(abs(w) <= 0.05 + 1e-9 for w in pw.weights.values())


def test_construct_portfolio_zero_turnover_against_self() -> None:
    scores, prices = make_predictive_universe()
    as_of = max(s.date for s in scores)
    pw = construct_portfolio(scores, prices, as_of)
    pw2 = construct_portfolio(scores, prices, as_of, prev_weights=pw.weights)
    assert pw2.turnover == pytest.approx(0.0, abs=1e-9)


def test_construct_portfolio_raises_without_scores_on_date() -> None:
    scores, prices = make_predictive_universe()
    with pytest.raises(ValueError, match="no combined scores"):
        construct_portfolio(scores, prices, as_of=date(2000, 1, 1))


def test_cvar_constructor_respects_constraints_and_labels_method() -> None:
    scores, prices = make_predictive_universe()
    as_of = max(s.date for s in scores)
    pw = construct_portfolio_cvar(scores, prices, as_of)
    assert isinstance(pw, PortfolioWeights)
    assert pw.construction_method == CVAR_CONSTRUCTION_METHOD
    assert violations(pw.weights, PortfolioConstraints()) == []
    assert abs(sum(pw.weights.values())) < 1e-6  # exact dollar-neutrality from the LP


def test_cvar_constructor_beats_or_matches_heuristic_cvar() -> None:
    # The exact LP should never produce a worse CVaR than the heuristic on the same data.
    scores, prices = make_predictive_universe()
    as_of = max(s.date for s in scores)
    lp = construct_portfolio_cvar(scores, prices, as_of, risk_aversion=0.0)
    heuristic = construct_portfolio(scores, prices, as_of)
    assert lp.construction_method == CVAR_CONSTRUCTION_METHOD
    assert heuristic.construction_method == CONSTRUCTION_METHOD
    assert lp.expected_cvar <= heuristic.expected_cvar + 1e-4
