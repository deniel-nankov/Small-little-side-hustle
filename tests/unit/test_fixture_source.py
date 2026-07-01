"""Unit tests for the fixture data source and the get_data_source factory."""

from __future__ import annotations

from datetime import date

import pytest
from config.settings import Settings
from src.data.contracts.schemas import DataSourceName
from src.data.source import FixtureSource, get_data_source

_TICKERS = ["AAPL", "MSFT"]
_START = date(2026, 1, 5)  # Monday
_END = date(2026, 1, 16)  # two trading weeks


def test_get_prices_returns_point_in_time_fixture_records() -> None:
    prices = FixtureSource().get_prices(_TICKERS, _START, _END)
    assert prices, "expected at least one price record"
    assert all(p.point_in_time for p in prices)
    assert all(p.data_source is DataSourceName.fixture for p in prices)
    # 10 business days * 2 tickers
    assert len(prices) == 20


def test_get_prices_skips_weekends() -> None:
    prices = FixtureSource().get_prices(["AAPL"], _START, _END)
    assert all(p.date.weekday() < 5 for p in prices)


def test_get_prices_is_deterministic() -> None:
    a = FixtureSource().get_prices(_TICKERS, _START, _END)
    b = FixtureSource().get_prices(_TICKERS, _START, _END)
    assert a == b


def test_get_prices_rejects_reversed_range() -> None:
    with pytest.raises(ValueError, match="precedes start"):
        FixtureSource().get_prices(["AAPL"], _END, _START)


def test_get_estimates_are_point_in_time() -> None:
    estimates = FixtureSource().get_estimates(_TICKERS, _START, _END)
    assert estimates
    assert all(e.is_point_in_time for e in estimates)
    assert all(e.currency == "USD" for e in estimates)


def test_factory_returns_fixture_source() -> None:
    cfg = Settings(_env_file=None, data_source="fixture")  # type: ignore[arg-type]
    assert isinstance(get_data_source(cfg), FixtureSource)


def test_factory_factset_requires_credentials() -> None:
    # The factory now builds FactSetSource; without credentials it fails loudly.
    from config.settings import MissingCredentialError

    cfg = Settings(_env_file=None, data_source="factset")  # type: ignore[arg-type]
    with pytest.raises(MissingCredentialError):
        get_data_source(cfg)
