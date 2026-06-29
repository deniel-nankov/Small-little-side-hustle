"""Unit tests for optimal signal weighting and combination."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from src.data.contracts.schemas import SignalScore
from src.signals.combination.optimal_weights import (
    _solve,
    combine_signals,
    optimal_weights,
)


def test_solve_known_linear_system() -> None:
    # [[2,1],[1,3]] x = [3,5] -> x = [0.8, 1.4]
    x = _solve([[2.0, 1.0], [1.0, 3.0]], [3.0, 5.0])
    assert x[0] == pytest.approx(0.8)
    assert x[1] == pytest.approx(1.4)


def test_solve_singular_raises() -> None:
    with pytest.raises(ValueError, match="singular"):
        _solve([[1.0, 1.0], [1.0, 1.0]], [1.0, 2.0])


def test_optimal_weights_normalized_to_unit_l1() -> None:
    dates = [date(2026, 1, 5) + timedelta(days=k) for k in range(10)]
    ic_p = {d: 0.05 + 0.001 * k for k, d in enumerate(dates)}
    ic_q = {d: 0.02 - 0.001 * k for k, d in enumerate(dates)}
    weights = optimal_weights({"P": ic_p, "Q": ic_q})
    assert sum(abs(w) for w in weights.values()) == pytest.approx(1.0)


def test_optimal_weights_equal_when_insufficient_history() -> None:
    weights = optimal_weights({"P": {date(2026, 1, 5): 0.05}, "Q": {date(2026, 1, 5): 0.02}})
    assert weights == {"P": 0.5, "Q": 0.5}


def test_optimal_weights_empty() -> None:
    assert optimal_weights({}) == {}


def test_combine_signals_weights_dominant_signal() -> None:
    dates = [date(2026, 1, 5), date(2026, 1, 6)]
    tickers = [f"T{i}" for i in range(6)]

    def _signal(raw_fn) -> list[SignalScore]:  # type: ignore[no-untyped-def]
        return [
            SignalScore(
                ticker=t,
                date=d,
                signal_name="s",
                signal_version="1.0.0",
                raw_score=float(raw_fn(i)),
                rank_score=0.5,
                data_inputs=["x"],
            )
            for d in dates
            for i, t in enumerate(tickers)
        ]

    p = _signal(lambda i: i)
    q = _signal(lambda i: -i)
    combined = combine_signals({"P": p, "Q": q}, {"P": 0.7, "Q": 0.3})
    assert combined
    assert all(0.0 <= s.rank_score <= 1.0 for s in combined)
    assert all(s.signal_name == "combined" for s in combined)
    first_day = {s.ticker: s.raw_score for s in combined if s.date == dates[0]}
    assert first_day["T5"] > first_day["T0"]  # P (positive, weight 0.7) dominates
