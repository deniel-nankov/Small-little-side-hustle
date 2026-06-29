"""Unit tests for the signal selector (de-duplication)."""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest
from src.data.contracts.schemas import SignalScore
from src.signals.combination.signal_selector import average_correlation, select_signals

_TICKERS = [f"T{i}" for i in range(6)]
_DATES = [date(2026, 1, 5) + timedelta(days=k) for k in range(20)]


def _signal(raw_fn) -> list[SignalScore]:  # type: ignore[no-untyped-def]
    return [
        SignalScore(
            ticker=t,
            date=d,
            signal_name="s",
            signal_version="1.0.0",
            raw_score=float(raw_fn(i, d)),
            rank_score=0.5,
            data_inputs=["x"],
        )
        for d in _DATES
        for i, t in enumerate(_TICKERS)
    ]


_A = _signal(lambda i, d: i)
_B = _signal(lambda i, d: i)  # identical to A
_C = _signal(lambda i, d: -i)  # perfectly anti-correlated with A
_D = _signal(lambda i, d: random.Random(f"{i}|{d}").random())  # noise


def test_average_correlation_identical_is_one() -> None:
    assert average_correlation(_A, _B) == pytest.approx(1.0)


def test_average_correlation_negated_is_minus_one() -> None:
    assert average_correlation(_A, _C) == pytest.approx(-1.0)


def test_drops_redundant_signal() -> None:
    result = select_signals({"A": _A, "B": _B})
    assert result.kept == ["A"]
    assert "B" in result.dropped


def test_drops_anticorrelated_signal() -> None:
    result = select_signals({"A": _A, "C": _C})
    assert result.kept == ["A"]
    assert "C" in result.dropped


def test_priority_controls_survivor() -> None:
    result = select_signals({"A": _A, "B": _B}, priority=["B", "A"])
    assert result.kept == ["B"]
    assert "A" in result.dropped


def test_keeps_uncorrelated_signals() -> None:
    result = select_signals({"A": _A, "D": _D})
    assert set(result.kept) == {"A", "D"}
