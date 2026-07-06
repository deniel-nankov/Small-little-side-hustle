"""Live smoke test for the free public data sources (opt-in; hits real endpoints).

Run with ``PUBLIC_LIVE_SMOKE=1 pytest tests/integration/test_public_connection.py``.
Skipped by default so CI and normal runs stay offline and deterministic.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from src.data.public.edgar import EdgarClient
from src.data.public.yahoo import YahooPriceClient

pytestmark = pytest.mark.skipif(
    os.environ.get("PUBLIC_LIVE_SMOKE") != "1",
    reason="live public-data smoke disabled (set PUBLIC_LIVE_SMOKE=1 to enable)",
)

_UA = "yale-alpha-fund research deniel.nankov@yale.edu"


def test_yahoo_live_prices() -> None:
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=30)
    bars = YahooPriceClient().get_prices(["AAPL"], start, end)
    assert len(bars) >= 15  # ~21 trading days in a month
    assert all(start <= b.date <= end for b in bars)
    assert all(b.low <= b.close <= b.high for b in bars)


def test_edgar_live_fundamentals() -> None:
    end = date.today()
    start = end - timedelta(days=550)
    rows = EdgarClient(_UA).get_fundamentals(["AAPL"], start, end)
    assert len(rows) >= 4  # at least a year of quarterly filings
    assert all(r.is_point_in_time for r in rows)
    assert all(start <= r.report_date <= end for r in rows)
    assert all(r.revenue > 1e10 for r in rows)  # Apple revenue is comfortably > $10B
