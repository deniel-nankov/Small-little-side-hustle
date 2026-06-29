"""Unit tests for the fixture source's fundamentals/ownership/supply-chain generators."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

import pytest
from src.data.source import FixtureSource

_TICKERS = ["AAPL", "MSFT", "NVDA"]
_START = date(2026, 1, 1)
_END = _START + timedelta(days=400)


def test_get_fundamentals_are_point_in_time_and_multi_period() -> None:
    records = FixtureSource().get_fundamentals(_TICKERS, _START, _END)
    assert records
    assert all(r.is_point_in_time for r in records)
    counts = Counter(r.ticker for r in records)
    assert all(c >= 3 for c in counts.values())  # >1y -> several quarters each


def test_get_fundamentals_is_deterministic() -> None:
    assert FixtureSource().get_fundamentals(
        _TICKERS, _START, _END
    ) == FixtureSource().get_fundamentals(_TICKERS, _START, _END)


def test_get_fundamentals_rejects_reversed_range() -> None:
    with pytest.raises(ValueError, match="precedes start"):
        FixtureSource().get_fundamentals(_TICKERS, _END, _START)


def test_get_ownership_fraction_within_bounds() -> None:
    records = FixtureSource().get_ownership(_TICKERS, _START, _END)
    assert records
    assert all(0.0 <= r.institutional_ownership_pct <= 1.0 for r in records)
    assert all(r.is_point_in_time for r in records)


def test_get_ownership_rejects_reversed_range() -> None:
    with pytest.raises(ValueError, match="precedes start"):
        FixtureSource().get_ownership(_TICKERS, _END, _START)


def test_get_supply_chain_has_no_self_links() -> None:
    links = FixtureSource().get_supply_chain(_TICKERS)
    assert links
    assert all(link.ticker != link.related_ticker for link in links)
    assert all(link.related_ticker in _TICKERS for link in links)


def test_get_supply_chain_single_ticker_is_empty() -> None:
    assert FixtureSource().get_supply_chain(["AAPL"]) == []
