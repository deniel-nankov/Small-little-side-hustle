"""Unit tests for the Information Coefficient calculator (ground-truth checks)."""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest
from src.data.contracts.schemas import DataSourceName, PriceData, SignalScore
from src.signals.validation.ic_calculator import (
    compute_forward_returns,
    daily_ics,
    evaluate_signal,
    spearman_ic,
    two_sided_t_pvalue,
)


def _score(ticker: str, d: date, raw: float) -> SignalScore:
    return SignalScore(
        ticker=ticker,
        date=d,
        signal_name="t",
        signal_version="1.0.0",
        raw_score=raw,
        rank_score=0.5,
        data_inputs=["x"],
    )


def _bar(ticker: str, d: date, close: float) -> PriceData:
    return PriceData(
        ticker=ticker,
        date=d,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1.0,
        adjusted_close=close,
        data_source=DataSourceName.fixture,
        point_in_time=True,
    )


# ---------------------------------------------------------------- spearman_ic
def test_spearman_ic_perfect_positive_is_one() -> None:
    assert spearman_ic([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == pytest.approx(1.0)


def test_spearman_ic_perfect_negative_is_minus_one() -> None:
    assert spearman_ic([1, 2, 3, 4, 5], [50, 40, 30, 20, 10]) == pytest.approx(-1.0)


def test_spearman_ic_is_rank_based_not_linear() -> None:
    # Monotonic-but-nonlinear relationship still has rank correlation 1.0.
    assert spearman_ic([1, 2, 3, 4], [1, 4, 9, 16]) == pytest.approx(1.0)


def test_ic_calculator_with_zero_variance_raises_error() -> None:
    with pytest.raises(ValueError, match="zero variance"):
        spearman_ic([1, 1, 1, 1], [1, 2, 3, 4])


# --------------------------------------------------------- two_sided_t_pvalue
def test_t_pvalue_at_zero_is_one() -> None:
    assert two_sided_t_pvalue(0.0, df=10) == pytest.approx(1.0)


def test_t_pvalue_matches_known_critical_value() -> None:
    # t = 2.228, df = 10 is the two-sided 5% critical value.
    assert two_sided_t_pvalue(2.228, df=10) == pytest.approx(0.05, abs=5e-3)


def test_t_pvalue_known_point() -> None:
    assert two_sided_t_pvalue(2.0, df=10) == pytest.approx(0.0734, abs=5e-3)


def test_t_pvalue_large_df_approaches_normal() -> None:
    assert two_sided_t_pvalue(1.959964, df=2_000_000) == pytest.approx(0.05, abs=5e-3)


# ----------------------------------------------------- compute_forward_returns
def test_compute_forward_returns_simple_series() -> None:
    d0 = date(2026, 1, 5)
    closes = [100.0, 110.0, 121.0, 133.1]
    bars = [_bar("AAPL", d0 + timedelta(days=i), c) for i, c in enumerate(closes)]
    fr = compute_forward_returns(bars, horizon_days=1)
    assert len(fr) == 3  # last bar has no forward observation
    assert fr[("AAPL", d0)] == pytest.approx(0.10)
    assert fr[("AAPL", d0 + timedelta(days=2))] == pytest.approx(0.10)


def test_compute_forward_returns_rejects_nonpositive_horizon() -> None:
    with pytest.raises(ValueError, match="horizon_days"):
        compute_forward_returns([], horizon_days=0)


# ------------------------------------------------------------- evaluate_signal
def _dates(n: int) -> list[date]:
    return [date(2026, 1, 5) + timedelta(days=i) for i in range(n)]


def test_evaluate_signal_perfect_ic() -> None:
    tickers = [f"T{i}" for i in range(6)]
    scores: list[SignalScore] = []
    fr: dict[tuple[str, date], float] = {}
    for d in _dates(3):
        for i, t in enumerate(tickers):
            scores.append(_score(t, d, float(i)))
            fr[(t, d)] = float(i)  # signal perfectly aligned with returns -> IC = 1
    report = evaluate_signal(scores, fr, min_cross_section=5)
    assert report.mean_ic == pytest.approx(1.0)
    assert report.positive_ic_ratio == 1.0
    assert report.n_periods == 3
    assert report.p_value == 0.0
    assert math.isinf(report.t_statistic)


def test_evaluate_signal_offsetting_ics_average_to_zero() -> None:
    tickers = [f"T{i}" for i in range(6)]
    d1, d2 = _dates(2)
    scores: list[SignalScore] = []
    fr: dict[tuple[str, date], float] = {}
    for i, t in enumerate(tickers):
        scores.append(_score(t, d1, float(i)))
        fr[(t, d1)] = float(i)  # IC = +1
        scores.append(_score(t, d2, float(i)))
        fr[(t, d2)] = float(5 - i)  # IC = -1
    report = evaluate_signal(scores, fr, min_cross_section=5)
    assert report.mean_ic == pytest.approx(0.0, abs=1e-9)
    assert report.positive_ic_ratio == 0.5
    assert report.n_periods == 2


def test_evaluate_signal_regime_breakdown() -> None:
    tickers = [f"T{i}" for i in range(6)]
    d1, d2 = _dates(2)
    scores: list[SignalScore] = []
    fr: dict[tuple[str, date], float] = {}
    for i, t in enumerate(tickers):
        scores += [_score(t, d1, float(i)), _score(t, d2, float(i))]
        fr[(t, d1)] = float(i)  # IC = +1 (bull)
        fr[(t, d2)] = float(5 - i)  # IC = -1 (bear)
    report = evaluate_signal(scores, fr, regimes={d1: "bull", d2: "bear"}, min_cross_section=5)
    assert report.by_regime["bull"] == pytest.approx(1.0)
    assert report.by_regime["bear"] == pytest.approx(-1.0)


def test_daily_ics_skips_small_cross_sections() -> None:
    tickers = [f"T{i}" for i in range(4)]  # below default min of 5
    d = _dates(1)[0]
    scores = [_score(t, d, float(i)) for i, t in enumerate(tickers)]
    fr = {(t, d): float(i) for i, t in enumerate(tickers)}
    assert daily_ics(scores, fr) == []


def test_evaluate_signal_raises_when_nothing_computable() -> None:
    tickers = [f"T{i}" for i in range(4)]
    d = _dates(1)[0]
    scores = [_score(t, d, float(i)) for i, t in enumerate(tickers)]
    fr = {(t, d): float(i) for i, t in enumerate(tickers)}
    with pytest.raises(ValueError, match="no date had a computable IC"):
        evaluate_signal(scores, fr)
