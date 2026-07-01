"""Integration test: real FactSet Global Prices request (small).

Requires FactSet API credentials; skips automatically when absent, so CI stays green
without secrets. When credentials are set, this exercises the live prices endpoint.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from config.settings import get_settings
from src.data.contracts.schemas import DataSourceName
from src.data.factset.source import FactSetSource

pytestmark = pytest.mark.integration


def test_factset_prices_returns_valid_contracts() -> None:
    cfg = get_settings()
    if not cfg.factset_client_id:
        pytest.skip("FactSet credentials not configured")

    source = FactSetSource.from_settings(cfg)
    end = date.today()
    start = end - timedelta(days=14)
    prices = source.get_prices(["AAPL"], start, end)

    assert prices, "expected at least one price bar for AAPL"
    assert all(p.data_source is DataSourceName.factset for p in prices)
    assert all(p.point_in_time for p in prices)
    assert all(p.close > 0 for p in prices)
