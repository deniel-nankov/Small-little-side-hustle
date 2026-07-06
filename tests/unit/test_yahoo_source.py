"""Unit tests for the Yahoo Finance public price client (ticket: public real-data sources)."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest
from src.data.contracts.schemas import DataSourceName
from src.data.public.client import PublicAPIError
from src.data.public.yahoo import YahooPriceClient

_GMTOFFSET = -14400  # US/Eastern during DST


def _ts(d: date) -> int:
    """Market-open-ish timestamp for ``d`` under the fixture gmtoffset."""
    return int(datetime(d.year, d.month, d.day, 13, 30, tzinfo=UTC).timestamp())


def _chart_body(
    *,
    opens: list[float | None],
    highs: list[float | None],
    lows: list[float | None],
    closes: list[float | None],
    volumes: list[float | None],
    adjcloses: list[float | None] | None,
    dates: list[date],
) -> bytes:
    indicators: dict = {
        "quote": [{"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}]
    }
    if adjcloses is not None:
        indicators["adjclose"] = [{"adjclose": adjcloses}]
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {"gmtoffset": _GMTOFFSET},
                    "timestamp": [_ts(d) for d in dates],
                    "indicators": indicators,
                }
            ],
            "error": None,
        }
    }
    return json.dumps(payload).encode()


_TWO_DAYS = _chart_body(
    opens=[100.0, 101.0],
    highs=[101.5, 102.0],
    lows=[99.5, 100.5],
    closes=[101.0, 101.5],
    volumes=[1_200_000, 900_000],
    adjcloses=[100.5, 101.0],
    dates=[date(2026, 3, 30), date(2026, 3, 31)],
)


def _canned(status: int, body: bytes):  # noqa: ANN202
    calls: list[tuple[str, dict[str, str]]] = []

    def transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        calls.append((url, headers))
        return status, body

    return transport, calls


def test_parses_chart_into_price_data() -> None:
    transport, _ = _canned(200, _TWO_DAYS)
    bars = YahooPriceClient(transport=transport).get_prices(
        ["AAPL"], date(2026, 3, 30), date(2026, 3, 31)
    )
    assert len(bars) == 2
    bar = bars[0]
    assert bar.ticker == "AAPL"
    assert bar.date == date(2026, 3, 30)
    assert (bar.open, bar.high, bar.low, bar.close) == (100.0, 101.5, 99.5, 101.0)
    assert bar.volume == 1_200_000
    assert bar.adjusted_close == 100.5  # the true dividend/split-adjusted close
    assert bar.data_source is DataSourceName.yahoo
    assert bar.point_in_time is True


def test_request_url_and_browser_user_agent() -> None:
    transport, calls = _canned(200, _TWO_DAYS)
    YahooPriceClient(transport=transport).get_prices(
        ["aapl"], date(2026, 3, 30), date(2026, 3, 31)
    )
    url, headers = calls[0]
    assert url.startswith("https://query1.finance.yahoo.com/v8/finance/chart/AAPL?")
    assert "interval=1d" in url
    assert "Mozilla" in headers["User-Agent"]  # Yahoo rejects default urllib UAs


def test_one_request_per_ticker() -> None:
    transport, calls = _canned(200, _TWO_DAYS)
    YahooPriceClient(transport=transport).get_prices(
        ["AAPL", "MSFT"], date(2026, 3, 30), date(2026, 3, 31)
    )
    assert len(calls) == 2


def test_null_halted_day_is_skipped() -> None:
    body = _chart_body(
        opens=[100.0, None],
        highs=[101.5, None],
        lows=[99.5, None],
        closes=[101.0, None],
        volumes=[1_200_000, None],
        adjcloses=[100.5, None],
        dates=[date(2026, 3, 30), date(2026, 3, 31)],
    )
    transport, _ = _canned(200, body)
    bars = YahooPriceClient(transport=transport).get_prices(
        ["AAPL"], date(2026, 3, 30), date(2026, 3, 31)
    )
    assert [b.date for b in bars] == [date(2026, 3, 30)]


def test_bars_outside_window_are_filtered() -> None:
    transport, _ = _canned(200, _TWO_DAYS)
    bars = YahooPriceClient(transport=transport).get_prices(
        ["AAPL"], date(2026, 3, 30), date(2026, 3, 30)
    )
    assert [b.date for b in bars] == [date(2026, 3, 30)]


def test_missing_adjclose_falls_back_to_close() -> None:
    body = _chart_body(
        opens=[100.0],
        highs=[101.5],
        lows=[99.5],
        closes=[101.0],
        volumes=[1_200_000],
        adjcloses=None,
        dates=[date(2026, 3, 30)],
    )
    transport, _ = _canned(200, body)
    bars = YahooPriceClient(transport=transport).get_prices(
        ["AAPL"], date(2026, 3, 30), date(2026, 3, 30)
    )
    assert bars[0].adjusted_close == bars[0].close


def test_empty_result_returns_empty() -> None:
    body = json.dumps({"chart": {"result": [], "error": None}}).encode()
    transport, _ = _canned(200, body)
    assert YahooPriceClient(transport=transport).get_prices(
        ["ZZZZ"], date(2026, 3, 30), date(2026, 3, 31)
    ) == []


def test_chart_error_payload_raises() -> None:
    body = json.dumps(
        {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data"}}}
    ).encode()
    transport, _ = _canned(200, body)
    with pytest.raises(PublicAPIError, match="Not Found"):
        YahooPriceClient(transport=transport).get_prices(
            ["ZZZZ"], date(2026, 3, 30), date(2026, 3, 31)
        )


def test_end_before_start_raises() -> None:
    transport, _ = _canned(200, _TWO_DAYS)
    with pytest.raises(ValueError, match="precedes"):
        YahooPriceClient(transport=transport).get_prices(
            ["AAPL"], date(2026, 4, 1), date(2026, 3, 1)
        )


def test_http_error_raises_public_api_error() -> None:
    transport, _ = _canned(404, b"not found")
    with pytest.raises(PublicAPIError, match="404"):
        YahooPriceClient(transport=transport).get_prices(
            ["AAPL"], date(2026, 3, 30), date(2026, 3, 31)
        )


def test_retries_transient_errors_then_succeeds() -> None:
    responses = [(500, b"boom"), (200, _TWO_DAYS)]
    naps: list[float] = []

    def transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        return responses.pop(0)

    client = YahooPriceClient(transport=transport, sleeper=naps.append)
    bars = client.get_prices(["AAPL"], date(2026, 3, 30), date(2026, 3, 31))
    assert len(bars) == 2
    assert len(naps) == 1  # one backoff nap between attempts
