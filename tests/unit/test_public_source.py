"""Unit tests for PublicSource + factory wiring (ticket: public real-data sources)."""

from __future__ import annotations

import json
from datetime import date

import pytest
from config.settings import DataSourceKind, Settings
from src.data.public.source import PublicSource
from src.data.source import get_data_source

_TICKERS_JSON = json.dumps(
    {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
).encode()

# One valid trading day (2026-03-30 13:30 UTC = 1774877400) in Yahoo chart shape.
_CHART = json.dumps(
    {
        "chart": {
            "result": [
                {
                    "meta": {"gmtoffset": -14400},
                    "timestamp": [1774877400],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100.0],
                                "high": [101.5],
                                "low": [99.5],
                                "close": [101.0],
                                "volume": [1200000],
                            }
                        ],
                        "adjclose": [{"adjclose": [100.5]}],
                    },
                }
            ],
            "error": None,
        }
    }
)


def _transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    if "finance.yahoo.com" in url:
        return 200, _CHART.encode()
    if "company_tickers" in url:
        return 200, _TICKERS_JSON
    return 200, json.dumps({"facts": {"us-gaap": {}}}).encode()


def _source() -> PublicSource:
    return PublicSource.from_settings(
        Settings(data_source=DataSourceKind.public), transport=_transport
    )


def test_get_prices_routes_to_yahoo() -> None:
    bars = _source().get_prices(["AAPL"], date(2026, 3, 30), date(2026, 3, 31))
    assert len(bars) == 1
    assert bars[0].ticker == "AAPL"


def test_get_fundamentals_routes_to_edgar() -> None:
    assert _source().get_fundamentals(["AAPL"], date(2026, 1, 1), date(2026, 6, 30)) == []


def test_unavailable_endpoints_raise_not_implemented() -> None:
    src = _source()
    with pytest.raises(NotImplementedError, match="estimates"):
        src.get_estimates(["AAPL"], date(2026, 1, 1), date(2026, 6, 30))
    with pytest.raises(NotImplementedError, match="ownership"):
        src.get_ownership(["AAPL"], date(2026, 1, 1), date(2026, 6, 30))
    with pytest.raises(NotImplementedError, match="supply"):
        src.get_supply_chain(["AAPL"])


def test_source_name() -> None:
    assert _source().name == "public"


def test_factory_returns_public_source() -> None:
    cfg = Settings(data_source=DataSourceKind.public)
    assert isinstance(get_data_source(cfg), PublicSource)


def test_public_source_needs_no_credentials() -> None:
    cfg = Settings(data_source=DataSourceKind.public)
    assert cfg.required_for_runtime() == []
