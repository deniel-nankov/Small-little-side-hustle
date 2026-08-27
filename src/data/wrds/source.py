"""WRDS-backed :class:`DataSource` — CRSP survivorship-bias-free prices (#55).

CRSP is the academic gold standard: it includes companies that later delisted, merged,
or went bankrupt, which fixes the survivorship bias our free sources carry. Four CRSP
conventions are handled here because each silently corrupts a backtest otherwise:

* **Ticker reuse.** 8,391 tickers map to more than one ``permno`` across history (a
  ticker is recycled after a company dies). ``permno`` is the only stable identifier,
  so resolution is DATE-AWARE via ``crsp.stocknames`` name windows.
* **Negative prices.** When no trade occurred, CRSP stores the bid/ask midpoint as a
  NEGATIVE ``prc``. The magnitude is the price; the sign is a quality flag.
* **Sparse OHLC.** ``openprc`` / ``askhi`` / ``bidlo`` are frequently null, and may be
  stale relative to ``prc``, so the bar is filled and clamped into a consistent range.
* **Dividends live in ``ret``, not ``prc``.** ``adjusted_close`` is therefore built by
  compounding CRSP's own total return and anchoring it to the final close, so the
  pct-change of ``adjusted_close`` reproduces CRSP total return exactly (the same
  convention Yahoo's ``adjclose`` uses).

Data currency: CRSP ends **2024-12-31**. For recent months, splice with
:class:`~src.data.public.source.PublicSource`.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from src.data.contracts.schemas import (
    DataSourceName,
    EstimateData,
    FundamentalData,
    Metric,
    PriceData,
)
from src.data.source.base import DataSource
from src.data.wrds.client import WRDSClient
from src.monitoring.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from config.settings import Settings

    from src.data.contracts.schemas import OwnershipData, SupplyChainLink

_log = get_logger(__name__)

STOCKNAMES_TABLE = "crsp.stocknames"
DSF_TABLE = "crsp.dsf"
FUNDQ_TABLE = "comp.fundq"
DET_EPSUS_TABLE = "ibes.det_epsus"

#: IBES forecast-period indicators for the four quarterly horizons (Q1..Q4).
QUARTERLY_FPI = frozenset({"6", "7", "8", "9"})

#: Last date covered by CRSP's daily stock file in Yale's subscription.
CRSP_COVERAGE_END = date(2024, 12, 31)


def _to_float(value: object) -> float | None:
    """Parse a WRDS cell to float; blanks/nulls/garbage become None."""
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _to_date(value: object) -> date | None:
    """Parse a WRDS ISO date cell; nulls become None."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class WRDSSource(DataSource):
    """Institutional data via the WRDS REST API (CRSP prices implemented)."""

    name = "wrds"

    def __init__(self, client: WRDSClient) -> None:
        """Initialize with a configured :class:`WRDSClient`."""
        self._client = client
        self._names: list[dict[str, Any]] | None = None

    @classmethod
    def from_settings(cls, cfg: Settings) -> WRDSSource:
        """Build from settings; requires ``WRDS_API_TOKEN``.

        Args:
            cfg: Runtime settings.

        Returns:
            A ready-to-use source.

        Raises:
            MissingCredentialError: if the token is unset.
        """
        cfg.require("wrds_api_token")
        assert cfg.wrds_api_token is not None  # noqa: S101 (require() guarantees this)
        return cls(WRDSClient(cfg.wrds_api_token.get_secret_value()))

    # --------------------------------------------------------- identifier resolution
    def _stocknames(self) -> list[dict[str, Any]]:
        """Return the CRSP name history (~83k rows), fetched once and cached.

        The API only honors filters on a table's indexed key, and ``ticker`` is NOT
        filterable on ``crsp.stocknames`` (it silently returns the whole table), so the
        table is pulled once in full and searched locally.
        """
        if self._names is None:
            self._names = self._client.get_rows(STOCKNAMES_TABLE)
            _log.info("wrds.stocknames_cached", rows=len(self._names))
        return self._names

    def permno_for(self, ticker: str, on_date: date) -> int | None:
        """Resolve ``ticker`` to the CRSP ``permno`` that held it on ``on_date``.

        Date-awareness is not optional: tickers are recycled, so a naive mapping would
        silently splice two different companies into one price series.

        Args:
            ticker: US ticker symbol (case-insensitive).
            on_date: The date the mapping must be valid for.

        Returns:
            The permno, or None when the ticker was unassigned on that date.
        """
        wanted = ticker.upper()
        for row in self._stocknames():
            if (row.get("ticker") or "").upper() != wanted:
                continue
            start, end = _to_date(row.get("namedt")), _to_date(row.get("nameenddt"))
            if start is not None and end is not None and start <= on_date <= end:
                return int(float(row["permno"]))
        return None

    def permno_in_window(self, ticker: str, start: date, end: date) -> int | None:
        """Resolve ``ticker`` to the permno that held it for most of ``[start, end]``.

        Resolving at a single date would silently drop every company that DIED inside
        the window (Lehman's ticker has no owner on 2008-12-31), which is precisely the
        survivorship bias CRSP exists to eliminate. Overlap-based resolution keeps them.

        Args:
            ticker: US ticker symbol (case-insensitive).
            start: Window start (inclusive).
            end: Window end (inclusive).

        Returns:
            The permno with the largest overlap, or None if the ticker never overlapped.
        """
        wanted = ticker.upper()
        best: tuple[int, int] | None = None  # (overlap_days, permno)
        for row in self._stocknames():
            if (row.get("ticker") or "").upper() != wanted:
                continue
            name_start, name_end = _to_date(row.get("namedt")), _to_date(row.get("nameenddt"))
            if name_start is None or name_end is None:
                continue
            overlap = (min(end, name_end) - max(start, name_start)).days
            if overlap < 0:
                continue
            candidate = (overlap, int(float(row["permno"])))
            if best is None or candidate[0] > best[0]:
                best = candidate
        return None if best is None else best[1]

    # ------------------------------------------------------------------------ prices
    def get_prices(self, tickers: Sequence[str], start: date, end: date) -> list[PriceData]:
        """See :meth:`DataSource.get_prices`. Served by CRSP daily stock file.

        Args:
            tickers: US ticker symbols; unresolvable ones are skipped with a warning.
            start: First date (inclusive).
            end: Last date (inclusive).

        Returns:
            Validated bars with dividend-and-split-adjusted ``adjusted_close``.

        Raises:
            ValueError: if ``end`` precedes ``start``.
        """
        if end < start:
            raise ValueError(f"end ({end}) precedes start ({start})")
        if start > CRSP_COVERAGE_END:
            _log.warning(
                "wrds.window_beyond_coverage", start=str(start), coverage_end=str(CRSP_COVERAGE_END)
            )
        out: list[PriceData] = []
        for ticker in tickers:
            # Window-based (not point) resolution so companies that delisted inside the
            # window — bankruptcies, acquisitions — are still returned.
            permno = self.permno_in_window(ticker, start, min(end, CRSP_COVERAGE_END))
            if permno is None:
                _log.warning(
                    "wrds.ticker_unresolved", ticker=ticker, window=f"{start}..{end}"
                )
                continue
            rows = self._client.get_rows(DSF_TABLE, filters={"permno": permno})
            out.extend(self._to_bars(ticker, rows, start, end))
        _log.info("wrds.get_prices", tickers=len(tickers), records=len(out))
        return out

    @staticmethod
    def _to_bars(
        ticker: str, rows: Sequence[dict[str, Any]], start: date, end: date
    ) -> list[PriceData]:
        """Convert CRSP daily rows into validated bars over ``[start, end]``."""
        parsed: list[tuple[date, float, float | None, dict[str, Any]]] = []
        for row in rows:
            day = _to_date(row.get("date"))
            price = _to_float(row.get("prc"))
            if day is None or price is None or price == 0.0:
                continue
            # A NEGATIVE prc means "no trade — this is the bid/ask midpoint".
            parsed.append((day, abs(price), _to_float(row.get("ret")), row))
        parsed.sort(key=lambda item: item[0])
        if not parsed:
            return []

        # Total-return index: compound CRSP's own `ret` (which includes dividends),
        # then anchor so the final value equals the final actual close.
        index = [1.0]
        for _, _, ret, _ in parsed[1:]:
            index.append(index[-1] * (1.0 + (ret or 0.0)))
        floor = min(index)
        if floor <= 0:  # a -100% return would zero the series; keep it strictly positive
            index = [max(v, 1e-9) for v in index]
        scale = parsed[-1][1] / index[-1]

        bars: list[PriceData] = []
        for i, (day, close, _, row) in enumerate(parsed):
            if not (start <= day <= end):
                continue
            open_ = abs(_to_float(row.get("openprc")) or close)
            high = abs(_to_float(row.get("askhi")) or max(open_, close))
            low = abs(_to_float(row.get("bidlo")) or min(open_, close))
            # CRSP high/low can be stale relative to prc; clamp so the contract holds.
            high = max(high, open_, close)
            low = min(low, open_, close)
            bars.append(
                PriceData(
                    ticker=ticker,
                    date=day,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=max(_to_float(row.get("vol")) or 0.0, 0.0),
                    adjusted_close=max(index[i] * scale, 1e-9),
                    data_source=DataSourceName.crsp,
                    point_in_time=True,
                )
            )
        return bars

    # ------------------------------------------------------------ not yet implemented
    def get_estimates(self, tickers: Sequence[str], start: date, end: date) -> list[EstimateData]:
        """See :meth:`DataSource.get_estimates`. Served by IBES detail (per-analyst).

        This is the raw material for TrueBeats: 34.5M INDIVIDUAL analyst estimates, not
        a blended consensus, so each forecast can be weighted by that analyst's own
        track record. ``anndats`` (the publication date) is the point-in-time date.

        Only quarterly forecast horizons (``fpi`` 6–9) are returned: annual and
        long-term-growth forecasts cannot be expressed by a contract that requires a
        fiscal quarter, and mixing horizons would corrupt a revision signal.

        Args:
            tickers: US ticker symbols (``ibes.det_epsus`` is filterable on ``ticker``).
            start: First announce date (inclusive).
            end: Last announce date (inclusive).

        Returns:
            Validated per-analyst EPS estimates.

        Raises:
            ValueError: if ``end`` precedes ``start``.
        """
        if end < start:
            raise ValueError(f"end ({end}) precedes start ({start})")
        out: list[EstimateData] = []
        for ticker in tickers:
            rows = self._client.get_rows(DET_EPSUS_TABLE, filters={"ticker": ticker.upper()})
            out.extend(self._to_estimates(ticker, rows, start, end))
        _log.info("wrds.get_estimates", tickers=len(tickers), records=len(out))
        return out

    @staticmethod
    def _to_estimates(
        ticker: str, rows: Sequence[dict[str, Any]], start: date, end: date
    ) -> list[EstimateData]:
        """Convert IBES detail rows into validated per-analyst estimates."""
        out: list[EstimateData] = []
        for row in rows:
            if str(row.get("fpi")) not in QUARTERLY_FPI or row.get("measure") != "EPS":
                continue
            announced = _to_date(row.get("anndats"))  # PIT: when it was published
            period_end = _to_date(row.get("fpedats"))
            value = _to_float(row.get("value"))
            analyst, broker = _to_float(row.get("analys")), _to_float(row.get("estimator"))
            if (
                announced is None
                or period_end is None
                or value is None
                or analyst is None
                or broker is None
                or not (start <= announced <= end)
            ):
                continue
            out.append(
                EstimateData(
                    ticker=ticker,
                    analyst_id=str(int(analyst)),
                    broker=str(int(broker)),
                    estimate_date=announced,
                    fiscal_year=period_end.year,
                    fiscal_quarter=(period_end.month - 1) // 3 + 1,
                    metric=Metric.eps,
                    value=value,
                    currency=str(row.get("curr") or "USD"),
                    is_point_in_time=True,
                    analyst_accuracy=None,  # derived downstream from realized errors
                )
            )
        return out

    def get_fundamentals(
        self, tickers: Sequence[str], start: date, end: date
    ) -> list[FundamentalData]:
        """See :meth:`DataSource.get_fundamentals`. Served by Compustat quarterly.

        Point-in-time comes from ``rdq`` — the date the company actually REPORTED —
        never ``datadate`` (the fiscal period end), which would leak roughly ten days
        of hindsight into every backtest.

        Args:
            tickers: US ticker symbols (``comp.fundq`` is filterable on ``tic``).
            start: First report date (inclusive).
            end: Last report date (inclusive).

        Returns:
            Validated quarterly fundamentals with a de-cumulated operating cash flow.

        Raises:
            ValueError: if ``end`` precedes ``start``.
        """
        if end < start:
            raise ValueError(f"end ({end}) precedes start ({start})")
        out: list[FundamentalData] = []
        for ticker in tickers:
            rows = self._client.get_rows(FUNDQ_TABLE, filters={"tic": ticker.upper()})
            out.extend(self._to_fundamentals(ticker, rows, start, end))
        _log.info("wrds.get_fundamentals", tickers=len(tickers), records=len(out))
        return out

    @staticmethod
    def _to_fundamentals(
        ticker: str, rows: Sequence[dict[str, Any]], start: date, end: date
    ) -> list[FundamentalData]:
        """Convert Compustat quarterly rows to contracts, de-cumulating cash flow."""
        usable: list[tuple[date, int, int, dict[str, Any]]] = []
        for row in rows:
            # Standard academic screen; restated/summary duplicates would double-count.
            if (
                row.get("datafmt") != "STD"
                or row.get("indfmt") != "INDL"
                or row.get("consol") != "C"
                or row.get("popsrc") != "D"
            ):
                continue
            reported = _to_date(row.get("rdq"))  # PIT date, NOT datadate
            fyear, fqtr = _to_float(row.get("fyearq")), _to_float(row.get("fqtr"))
            if reported is None or fyear is None or fqtr is None:
                continue  # a row with no report date has no point-in-time meaning
            usable.append((reported, int(fyear), int(fqtr), row))

        # oancfy is YEAR-TO-DATE and resets each fiscal year, so the quarterly figure is
        # the difference against the previous quarter OF THE SAME FISCAL YEAR.
        usable.sort(key=lambda item: (item[1], item[2]))
        prior_ytd: dict[int, tuple[int, float]] = {}  # fyear -> (fqtr, ytd)
        out: list[FundamentalData] = []
        for reported, fyear, fqtr, row in usable:
            ytd = _to_float(row.get("oancfy"))
            quarterly_ocf: float | None = None
            if ytd is not None:
                previous = prior_ytd.get(fyear)
                quarterly_ocf = ytd if previous is None else ytd - previous[1]
                prior_ytd[fyear] = (fqtr, ytd)

            assets, income, revenue = (
                _to_float(row.get("atq")),
                _to_float(row.get("niq")),
                _to_float(row.get("revtq")),
            )
            if (
                not (start <= reported <= end)
                or assets is None
                or assets <= 0
                or income is None
                or revenue is None
                or revenue < 0
                or quarterly_ocf is None
                or not 1 <= fqtr <= 4
            ):
                continue
            out.append(
                FundamentalData(
                    ticker=ticker,
                    report_date=reported,
                    fiscal_year=fyear,
                    fiscal_quarter=fqtr,
                    total_assets=assets,
                    net_income=income,
                    operating_cash_flow=quarterly_ocf,
                    revenue=revenue,
                    is_point_in_time=True,
                )
            )
        return out

    def get_ownership(self, tickers: Sequence[str], start: date, end: date) -> list[OwnershipData]:
        """Pending: ``tfn.s34`` by 8-char CUSIP, point-in-time via ``fdate``."""
        raise NotImplementedError("Thomson 13F ownership lands in a later step (#55)")

    def get_supply_chain(self, tickers: Sequence[str]) -> list[SupplyChainLink]:
        """Pending: ``revere.supply_chain`` with ``revenue_percent`` as the edge weight."""
        raise NotImplementedError("Revere supply chain lands in a later step (#55)")
