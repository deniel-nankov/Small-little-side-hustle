"""Free daily OHLCV prices from Yahoo Finance's chart API (no key, no account).

The ``v8/finance/chart`` endpoint serves daily bars as JSON over https with a plain
browser User-Agent — including a genuine dividend/split-adjusted close (``adjclose``),
which Stooq never offered. Unofficial but stable for years (it is what ``yfinance``
wraps); the injectable transport keeps us unit-testable and swap-ready regardless.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from src.data.contracts.schemas import DataSourceName, PriceData
from src.data.public.client import HttpClient, PublicAPIError, Transport
from src.monitoring.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_log = get_logger(__name__)

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"

#: Yahoo rejects default urllib UAs; a plain browser UA is required.
_UA = "Mozilla/5.0 (research; yale-alpha-fund)"


class YahooPriceClient:
    """Fetches daily bars from Yahoo Finance and returns validated :class:`PriceData`."""

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize the client.

        Args:
            transport: Optional injected transport (for tests); defaults to urllib.
            sleeper: Sleep function for retry backoff (injectable for tests).
        """
        self._http = HttpClient(
            {"User-Agent": _UA, "Accept": "application/json"},
            transport=transport,
            sleeper=sleeper,
        )

    def get_prices(self, tickers: Sequence[str], start: date, end: date) -> list[PriceData]:
        """Return daily OHLCV bars for ``tickers`` over ``[start, end]`` inclusive.

        Args:
            tickers: US ticker symbols.
            start: First date (inclusive).
            end: Last date (inclusive).

        Returns:
            A list of :class:`PriceData`; days Yahoo reports as null (halts) are skipped.

        Raises:
            ValueError: if ``end`` precedes ``start``.
            PublicAPIError: on HTTP failure or a chart-level error payload.
        """
        if end < start:
            raise ValueError(f"end ({end}) precedes start ({start})")
        period1 = int(datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp())
        end_next = end + timedelta(days=1)  # period2 is exclusive
        period2 = int(datetime(end_next.year, end_next.month, end_next.day, tzinfo=UTC).timestamp())

        out: list[PriceData] = []
        for ticker in tickers:
            url = (
                f"{CHART_URL.format(ticker=ticker.upper())}"
                f"?period1={period1}&period2={period2}&interval=1d&events=div%2Csplit"
            )
            payload = json.loads(self._http.get_bytes(url))
            out.extend(self._parse_chart(ticker, payload, start, end))
        _log.debug("yahoo.get_prices", tickers=len(tickers), records=len(out))
        return out

    @staticmethod
    def _parse_chart(
        ticker: str, payload: dict[str, Any], start: date, end: date
    ) -> list[PriceData]:
        """Parse one chart payload into bars, skipping null (halted) days."""
        chart = payload.get("chart", {})
        if chart.get("error"):
            raise PublicAPIError(0, json.dumps(chart["error"]).encode())
        results = chart.get("result") or []
        if not results:
            _log.warning("yahoo.no_data", ticker=ticker)
            return []
        result = results[0]
        gmtoffset = int(result.get("meta", {}).get("gmtoffset", 0))
        timestamps: list[int] = result.get("timestamp") or []
        quote = result["indicators"]["quote"][0]
        adjclose_block = result["indicators"].get("adjclose") or [{}]
        adjclose: list[float | None] = adjclose_block[0].get("adjclose") or []

        bars: list[PriceData] = []
        for i, ts in enumerate(timestamps):
            fields = (
                quote["open"][i],
                quote["high"][i],
                quote["low"][i],
                quote["close"][i],
                quote["volume"][i],
            )
            if any(v is None for v in fields):
                continue  # halted / no-trade day
            bar_date = datetime.fromtimestamp(ts + gmtoffset, tz=UTC).date()
            if not (start <= bar_date <= end):
                continue
            close_val = float(fields[3])
            adj_raw = adjclose[i] if i < len(adjclose) else None
            bars.append(
                PriceData(
                    ticker=ticker,
                    date=bar_date,
                    open=float(fields[0]),
                    high=float(fields[1]),
                    low=float(fields[2]),
                    close=close_val,
                    volume=float(fields[4]),
                    adjusted_close=float(adj_raw) if adj_raw is not None else close_val,
                    data_source=DataSourceName.yahoo,
                    point_in_time=True,
                )
            )
        return bars
