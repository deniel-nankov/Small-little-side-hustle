"""Unit tests for the TrueBeats DIY earnings-surprise signal."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from src.data.contracts.schemas import EstimateData, Metric, SignalScore
from src.data.source import FixtureSource
from src.signals.construction.truebeats import compute_truebeats

AS_OF = date(2026, 1, 5)


def _est(
    ticker: str,
    analyst_id: str,
    value: float,
    accuracy: float | None,
    *,
    d: date = AS_OF,
    point_in_time: bool = True,
) -> EstimateData:
    return EstimateData(
        ticker=ticker,
        analyst_id=analyst_id,
        broker="BRK01",
        estimate_date=d,
        fiscal_year=2026,
        fiscal_quarter=1,
        metric=Metric.eps,
        value=value,
        currency="USD",
        is_point_in_time=point_in_time,
        analyst_accuracy=accuracy,
    )


def _by_ticker(scores: list[SignalScore]) -> dict[str, SignalScore]:
    return {s.ticker: s for s in scores}


def test_expert_beat_ranks_accuracy_weighted_consensus_higher() -> None:
    # BEAT: the most accurate analyst is the most bullish -> accuracy-weighted consensus
    # sits above the naive mean -> predicted positive surprise.
    # MISS: the most accurate analyst is the most bearish -> predicted negative surprise.
    # NEUTRAL: balanced. No analyst ids are shared, so the trend component is 0 for all.
    estimates = [
        _est("BEAT", "B1", 12.0, 0.9),
        _est("BEAT", "B2", 10.0, 0.5),
        _est("BEAT", "B3", 8.0, 0.1),
        _est("MISS", "M1", 8.0, 0.9),
        _est("MISS", "M2", 10.0, 0.5),
        _est("MISS", "M3", 12.0, 0.1),
        _est("NEUTRAL", "N1", 9.0, 0.5),
        _est("NEUTRAL", "N2", 10.0, 0.5),
        _est("NEUTRAL", "N3", 11.0, 0.5),
    ]
    scores = _by_ticker(compute_truebeats(estimates, as_of=AS_OF))
    assert scores["BEAT"].rank_score > scores["MISS"].rank_score
    assert scores["BEAT"].raw_score > scores["MISS"].raw_score


def test_output_is_one_valid_score_per_ticker() -> None:
    estimates = [
        _est("AAA", "A1", 10.0, 0.6),
        _est("AAA", "A2", 11.0, 0.4),
        _est("BBB", "B1", 9.0, 0.6),
        _est("BBB", "B2", 8.0, 0.4),
    ]
    scores = compute_truebeats(estimates, as_of=AS_OF)
    assert {s.ticker for s in scores} == {"AAA", "BBB"}
    assert all(0.0 <= s.rank_score <= 1.0 for s in scores)
    assert all(s.signal_name == "truebeats" for s in scores)


def test_is_deterministic() -> None:
    estimates = [
        _est("AAA", "A1", 10.0, 0.6),
        _est("AAA", "A2", 11.0, 0.4),
        _est("BBB", "B1", 9.0, 0.6),
    ]
    assert compute_truebeats(estimates, as_of=AS_OF) == compute_truebeats(estimates, as_of=AS_OF)


def test_point_in_time_filter_excludes_future_estimates() -> None:
    future = AS_OF + timedelta(days=10)
    estimates = [
        _est("AAA", "A1", 10.0, 0.6),
        _est("AAA", "A2", 11.0, 0.4),
        _est("FUTURE", "F1", 5.0, 0.9, d=future),  # only future-dated -> excluded
    ]
    tickers = {s.ticker for s in compute_truebeats(estimates, as_of=AS_OF)}
    assert tickers == {"AAA"}


def test_non_point_in_time_estimate_raises() -> None:
    estimates = [
        _est("AAA", "A1", 10.0, 0.6, point_in_time=False),
        _est("AAA", "A2", 11.0, 0.4),
    ]
    with pytest.raises(ValueError, match="point-in-time"):
        compute_truebeats(estimates, as_of=AS_OF)


def test_runs_on_fixture_source_estimates() -> None:
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOG"]
    estimates = FixtureSource().get_estimates(tickers, AS_OF, AS_OF + timedelta(days=5))
    scores = compute_truebeats(estimates, as_of=AS_OF)
    assert {s.ticker for s in scores} == set(tickers)
    assert all(0.0 <= s.rank_score <= 1.0 for s in scores)
