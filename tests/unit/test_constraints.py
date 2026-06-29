"""Unit tests for portfolio constraints."""

from __future__ import annotations

import pytest
from src.portfolio.constraints import PortfolioConstraints, enforce, turnover, violations


def test_enforce_caps_positions_and_neutralizes() -> None:
    constraints = PortfolioConstraints(max_position=0.1, max_gross=1.0, dollar_neutral=True)
    weights = enforce({"A": 0.5, "B": 0.3, "C": -0.2}, constraints)
    assert all(abs(w) <= 0.1 + 1e-9 for w in weights.values())
    assert sum(abs(w) for w in weights.values()) <= 1.0 + 1e-9
    assert violations(weights, constraints) == []


def test_enforce_scales_gross_down() -> None:
    constraints = PortfolioConstraints(max_position=1.0, max_gross=1.0, dollar_neutral=False)
    weights = enforce({"A": 2.0, "B": -2.0}, constraints)
    assert sum(abs(w) for w in weights.values()) == 1.0


def test_enforce_empty_returns_empty() -> None:
    assert enforce({}, PortfolioConstraints()) == {}


def test_turnover_against_flat_book() -> None:
    assert turnover({"A": 0.1, "B": -0.1}, None) == 0.2


def test_turnover_against_previous() -> None:
    assert turnover({"A": 0.1, "B": -0.1}, {"A": 0.1, "C": 0.05}) == pytest.approx(0.15)


def test_violations_flags_oversized_position() -> None:
    constraints = PortfolioConstraints(max_position=0.1, dollar_neutral=False)
    problems = violations({"A": 0.5}, constraints)
    assert any("max_position" in p for p in problems)
