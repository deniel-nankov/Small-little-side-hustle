"""Unit tests for the FactSet-backed DataSource (ticket: FactSetSource, Stage 2)."""

from __future__ import annotations

import json
from datetime import date

import pytest
from config.settings import MissingCredentialError, Settings
from src.data.contracts.schemas import DataSourceName
from src.data.factset.client import FactSetClient
from src.data.factset.source import FactSetSource

_OHLC = {
    "data": [
        {
            "requestId": "AAPL-US",
            "date": "2021-08-23",
            "price": 366.61,
            "priceOpen": 370.06,
            "priceHigh": 372.23,
            "priceLow": 366.45,
            "volume": 157303,
            "currency": "USD",
            "fsymId": "SQFMK3-R",
        }
    ]
}
_ADJUSTED = {
    "data": [{"requestId": "AAPL-US", "date": "2021-08-23", "price": 360.0, "currency": "USD"}]
}


def _transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
    body = _ADJUSTED if "DIV_SPIN_SPLITS" in url else _OHLC
    return 200, json.dumps(body).encode()


def _source(transport=_transport) -> FactSetSource:  # type: ignore[no-untyped-def]
    client = FactSetClient("uid", "secret", transport=transport, sleeper=lambda _s: None)
    return FactSetSource(client)


def test_get_prices_maps_response_to_contract() -> None:
    prices = _source().get_prices(["AAPL"], date(2021, 8, 23), date(2021, 8, 23))
    assert len(prices) == 1
    p = prices[0]
    assert p.ticker == "AAPL"
    assert (p.open, p.high, p.low, p.close) == (370.06, 372.23, 366.45, 366.61)
    assert p.volume == 157303
    assert p.adjusted_close == 360.0  # from the DIV_SPIN_SPLITS call
    assert p.data_source is DataSourceName.factset
    assert p.point_in_time is True


def test_get_prices_skips_invalid_rows() -> None:
    bad = {"data": [{"requestId": "AAPL-US", "date": "2021-08-23", "price": -5.0}]}

    def transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        body = {"data": []} if "DIV_SPIN_SPLITS" in url else bad
        return 200, json.dumps(body).encode()

    assert _source(transport).get_prices(["AAPL"], date(2021, 8, 23), date(2021, 8, 23)) == []


def test_get_prices_rejects_reversed_range() -> None:
    with pytest.raises(ValueError, match="precedes start"):
        _source().get_prices(["AAPL"], date(2021, 8, 24), date(2021, 8, 23))


def test_unimplemented_methods_raise() -> None:
    src = _source()
    with pytest.raises(NotImplementedError):
        src.get_estimates(["AAPL"], date(2021, 1, 1), date(2021, 1, 2))
    with pytest.raises(NotImplementedError):
        src.get_fundamentals(["AAPL"], date(2021, 1, 1), date(2021, 1, 2))
    with pytest.raises(NotImplementedError):
        src.get_ownership(["AAPL"], date(2021, 1, 1), date(2021, 1, 2))
    with pytest.raises(NotImplementedError):
        src.get_supply_chain(["AAPL"])


def test_from_settings_requires_credentials() -> None:
    cfg = Settings(_env_file=None, data_source="factset")  # type: ignore[arg-type]
    with pytest.raises(MissingCredentialError):
        FactSetSource.from_settings(cfg)
