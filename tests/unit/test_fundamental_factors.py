"""Unit tests for the fundamental-factor signal."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from src.data.contracts.schemas import FundamentalData
from src.data.source import FixtureSource
from src.signals.construction.fundamental_factors import compute_fundamental_factors

AS_OF = date(2026, 6, 1)


def _fund(ticker: str, report_date: date, ni: float, ocf: float, revenue: float) -> FundamentalData:
    return FundamentalData(
        ticker=ticker,
        report_date=report_date,
        fiscal_year=report_date.year,
        fiscal_quarter=((report_date.month - 1) // 3) + 1,
        total_assets=1000.0,
        net_income=ni,
        operating_cash_flow=ocf,
        revenue=revenue,
        is_point_in_time=True,
    )


def _series(ticker: str, revenues: list[float], ni: float, ocf: float) -> list[FundamentalData]:
    start = date(2025, 9, 1)
    return [
        _fund(ticker, start + timedelta(days=91 * i), ni, ocf, rev)
        for i, rev in enumerate(revenues)
    ]


def test_high_quality_fundamentals_rank_above_low_quality() -> None:
    # GOOD: high ROA, low (negative) accruals, accelerating revenue.
    # BAD:  low ROA, high accruals, decelerating revenue.
    records = (
        _series("GOOD", [100.0, 110.0, 130.0], ni=200.0, ocf=250.0)
        + _series("BAD", [130.0, 140.0, 145.0], ni=50.0, ocf=10.0)
        + _series("MID", [100.0, 105.0, 110.0], ni=100.0, ocf=100.0)
    )
    scores = {s.ticker: s for s in compute_fundamental_factors(records, as_of=AS_OF)}
    assert scores["GOOD"].rank_score > scores["BAD"].rank_score


def test_point_in_time_filter_excludes_future_periods() -> None:
    records = _series("AAA", [100.0, 110.0, 120.0], ni=50.0, ocf=60.0)
    records.append(_fund("FUTURE", AS_OF + timedelta(days=120), 50.0, 60.0, 100.0))
    tickers = {s.ticker for s in compute_fundamental_factors(records, as_of=AS_OF)}
    assert tickers == {"AAA"}


def test_non_point_in_time_raises() -> None:
    records = _series("AAA", [100.0, 110.0, 120.0], ni=50.0, ocf=60.0)
    bad = records[0].model_copy(update={"is_point_in_time": False})
    with pytest.raises(ValueError, match="point-in-time"):
        compute_fundamental_factors([bad, *records[1:]], as_of=AS_OF)


def test_runs_on_fixture_source() -> None:
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOG"]
    start = date(2024, 1, 1)
    records = FixtureSource().get_fundamentals(tickers, start, AS_OF)
    scores = compute_fundamental_factors(records, as_of=AS_OF)
    assert {s.ticker for s in scores} == set(tickers)
    assert all(0.0 <= s.rank_score <= 1.0 for s in scores)
