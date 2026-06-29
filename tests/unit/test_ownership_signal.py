"""Unit tests for the institutional-ownership momentum signal."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from src.data.contracts.schemas import OwnershipData
from src.data.source import FixtureSource
from src.signals.construction.ownership_signal import compute_ownership_momentum

AS_OF = date(2026, 6, 1)


def _own(ticker: str, d: date, pct: float) -> OwnershipData:
    return OwnershipData(
        ticker=ticker,
        as_of_date=d,
        institutional_ownership_pct=pct,
        institution_count=100,
        is_point_in_time=True,
    )


def test_rising_ownership_ranks_above_falling() -> None:
    old = AS_OF - timedelta(days=150)
    new = AS_OF - timedelta(days=5)
    records = [
        _own("RISING", old, 0.30),
        _own("RISING", new, 0.60),
        _own("FALLING", old, 0.60),
        _own("FALLING", new, 0.30),
        _own("FLAT", old, 0.45),
        _own("FLAT", new, 0.45),
    ]
    scores = {s.ticker: s for s in compute_ownership_momentum(records, as_of=AS_OF)}
    assert scores["RISING"].rank_score > scores["FALLING"].rank_score


def test_point_in_time_filter_excludes_future_snapshots() -> None:
    records = [
        _own("AAA", AS_OF - timedelta(days=120), 0.4),
        _own("AAA", AS_OF - timedelta(days=5), 0.5),
        _own("FUTURE", AS_OF + timedelta(days=10), 0.9),
    ]
    assert {s.ticker for s in compute_ownership_momentum(records, as_of=AS_OF)} == {"AAA"}


def test_non_point_in_time_raises() -> None:
    records = [_own("AAA", AS_OF - timedelta(days=5), 0.4)]
    bad = records[0].model_copy(update={"is_point_in_time": False})
    with pytest.raises(ValueError, match="point-in-time"):
        compute_ownership_momentum([bad], as_of=AS_OF)


def test_nonpositive_lookback_raises() -> None:
    with pytest.raises(ValueError, match="lookback_days"):
        compute_ownership_momentum([], as_of=AS_OF, lookback_days=0)


def test_runs_on_fixture_source() -> None:
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOG"]
    start = AS_OF - timedelta(days=365)
    records = FixtureSource().get_ownership(tickers, start, AS_OF)
    scores = compute_ownership_momentum(records, as_of=AS_OF)
    assert {s.ticker for s in scores} == set(tickers)
    assert all(0.0 <= s.rank_score <= 1.0 for s in scores)
