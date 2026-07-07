"""Free point-in-time fundamentals from SEC EDGAR's companyfacts XBRL feed.

EDGAR is the one free source with GENUINE point-in-time semantics: every XBRL value
carries the ``filed`` date of the filing that disclosed it. Point-in-time rules applied
here (the non-negotiables):

* ``report_date`` = the latest ``filed`` date across the four concepts — the first day
  ALL of them were knowable. Never the fiscal period end.
* Original filings win: a restatement (e.g. a 10-Q/A filed months later) must NOT
  rewrite the value history — we keep the earliest-filed value per concept/period.
* When a 10-Q reports both the 3-month and year-to-date durations of a flow concept for
  the same fiscal period, the shortest (quarterly) duration is used.
* Filings also disclose PRIOR-YEAR comparatives under the same fy/fp tag: at equal filed
  date and duration, the latest period ``end`` wins, so the current period is used.
* Tag priority (e.g. ``Revenues`` over ``RevenueFromContractWithCustomer…``) is resolved
  per period — a tag that only carries legacy periods never shadows recent ones.

SEC fair-access rules require an identifying ``User-Agent`` (name + contact email);
set ``EDGAR_USER_AGENT`` in ``.env``.
"""

from __future__ import annotations

import json
import time
from datetime import date
from typing import TYPE_CHECKING, Any

from src.data.contracts.schemas import FundamentalData
from src.data.public.client import HttpClient, PublicAPIError, Transport
from src.monitoring.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_log = get_logger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

#: Polite spacing between requests (SEC allows 10 req/s; exceeding it earns a ~10-minute
#: 403 "Request Rate Threshold Exceeded" ban for the whole client IP).
POLITE_INTERVAL_S = 0.25

#: us-gaap concept tags per FundamentalData field; first tag found wins.
_CONCEPTS: dict[str, tuple[str, ...]] = {
    "total_assets": ("Assets",),
    "net_income": ("NetIncomeLoss",),
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ),
}

_QUARTER = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 4}
_ORIGINAL_FORMS = frozenset({"10-Q", "10-K"})  # amendments (…/A) never rewrite history


class EdgarClient:
    """Fetches point-in-time fundamentals from EDGAR companyfacts."""

    def __init__(
        self,
        user_agent: str,
        *,
        transport: Transport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize the client.

        Args:
            user_agent: SEC-required identification, e.g. ``"project-name you@email"``.
            transport: Optional injected transport (for tests); defaults to urllib.
            sleeper: Sleep function for retry backoff (injectable for tests).
        """
        self._http = HttpClient(
            {"User-Agent": user_agent, "Accept": "application/json"},
            transport=transport,
            min_interval=POLITE_INTERVAL_S,
            sleeper=sleeper,
        )
        self._listing: list[dict[str, Any]] | None = None

    def _get_listing(self) -> list[dict[str, Any]]:
        """Return the SEC company/ticker listing (fetched once, order preserved)."""
        if self._listing is None:
            raw = json.loads(self._http.get_bytes(TICKERS_URL))
            self._listing = [raw[key] for key in sorted(raw, key=int)]
        return self._listing

    def cik_for(self, ticker: str) -> int:
        """Return the SEC CIK for ``ticker`` (ticker map fetched once, then cached).

        Args:
            ticker: US ticker symbol (case-insensitive).

        Returns:
            The integer CIK.

        Raises:
            PublicAPIError: if the ticker is unknown to EDGAR.
        """
        wanted = ticker.upper()
        for row in self._get_listing():
            if row["ticker"].upper() == wanted:
                return int(row["cik_str"])
        raise PublicAPIError(404, f"ticker {wanted} not found on EDGAR".encode())

    def top_tickers(self, n: int) -> list[str]:
        """Return the first ``n`` tickers from SEC's listing (~largest companies).

        The SEC serves ``company_tickers.json`` ordered roughly by market cap, so the
        head of the file is a usable large-cap universe with no extra data source.
        Secondary share classes (same CIK, e.g. GOOG next to GOOGL) are collapsed to
        the first-listed ticker.

        NOTE: this is TODAY'S listing — applying it to a historical backtest carries
        survivorship bias (companies that shrank or delisted are missing).

        Args:
            n: How many tickers to return (> 0).

        Returns:
            Up to ``n`` uppercase tickers in listing order.

        Raises:
            ValueError: if ``n`` is not positive.
        """
        if n <= 0:
            raise ValueError(f"n must be > 0, got {n}")
        out: list[str] = []
        seen_ciks: set[int] = set()
        for row in self._get_listing():
            cik = int(row["cik_str"])
            if cik in seen_ciks:
                continue
            seen_ciks.add(cik)
            out.append(row["ticker"].upper())
            if len(out) == n:
                break
        return out

    def get_fundamentals(
        self, tickers: Sequence[str], start: date, end: date
    ) -> list[FundamentalData]:
        """Return point-in-time fundamentals FILED within ``[start, end]``.

        Args:
            tickers: US ticker symbols.
            start: First filed date (inclusive).
            end: Last filed date (inclusive).

        Returns:
            One :class:`FundamentalData` per ticker per fiscal period whose four
            concepts were all disclosed within the window. Incomplete periods are
            skipped (never partially filled).

        Raises:
            ValueError: if ``end`` precedes ``start``.
            PublicAPIError: on HTTP failure or unknown ticker.
        """
        if end < start:
            raise ValueError(f"end ({end}) precedes start ({start})")
        out: list[FundamentalData] = []
        for ticker in tickers:
            cik = self.cik_for(ticker)
            facts = json.loads(self._http.get_bytes(FACTS_URL.format(cik=cik)))
            gaap: dict[str, Any] = facts.get("facts", {}).get("us-gaap", {})
            out.extend(self._rows_for(ticker, gaap, start, end))
        _log.debug("edgar.get_fundamentals", tickers=len(tickers), records=len(out))
        return out

    @classmethod
    def _rows_for(
        cls, ticker: str, gaap: dict[str, Any], start: date, end: date
    ) -> list[FundamentalData]:
        """Join the four concepts per fiscal period, honoring the PIT rules above."""
        # (fy, fp) -> field -> the winning raw XBRL entry.
        # Tag priority is resolved PER PERIOD: a higher-priority tag that only carries
        # legacy periods (e.g. Apple's pre-2018 "Revenues") must not shadow recent
        # periods reported under a newer tag.
        periods: dict[tuple[int, str], dict[str, dict[str, Any]]] = {}
        for field, tags in _CONCEPTS.items():
            filled: set[tuple[int, str]] = set()
            for tag in tags:
                tag_keys: set[tuple[int, str]] = set()
                for entry in cls._usd_entries(gaap, tag):
                    key = (int(entry["fy"]), str(entry["fp"]))
                    if key in filled:
                        continue  # a higher-priority tag already covers this period
                    tag_keys.add(key)
                    chosen = periods.setdefault(key, {}).get(field)
                    if chosen is None or cls._beats(entry, chosen):
                        periods[key][field] = entry
                filled |= tag_keys

        rows: list[FundamentalData] = []
        for (fy, fp), fields in sorted(periods.items()):
            if set(fields) != set(_CONCEPTS):
                continue  # incomplete period — never emit partial fundamentals
            report_date = max(date.fromisoformat(e["filed"]) for e in fields.values())
            if not (start <= report_date <= end):
                continue
            rows.append(
                FundamentalData(
                    ticker=ticker,
                    report_date=report_date,
                    fiscal_year=fy,
                    fiscal_quarter=_QUARTER.get(fp, 4),
                    total_assets=float(fields["total_assets"]["val"]),
                    net_income=float(fields["net_income"]["val"]),
                    operating_cash_flow=float(fields["operating_cash_flow"]["val"]),
                    revenue=float(fields["revenue"]["val"]),
                    is_point_in_time=True,
                )
            )
        return rows

    @staticmethod
    def _usd_entries(gaap: dict[str, Any], tag: str) -> list[dict[str, Any]]:
        """Return original-filing USD entries for one concept tag."""
        units = gaap.get(tag, {}).get("units", {})
        return [
            e
            for e in units.get("USD", [])
            if e.get("form") in _ORIGINAL_FORMS and e.get("fy") is not None and e.get("fp")
        ]

    @staticmethod
    def _beats(candidate: dict[str, Any], chosen: dict[str, Any]) -> bool:
        """True if ``candidate`` should replace the currently chosen entry.

        Preference order: earlier ``filed`` first (the original disclosure wins over any
        later re-disclosure); among same-day filings, the shorter duration wins (the
        3-month flow beats the year-to-date flow reported in the same 10-Q); at equal
        duration, the latest period ``end`` wins (the CURRENT period beats the prior-year
        comparative disclosed in the same filing under the same fy/fp tag).
        """
        cand_filed = date.fromisoformat(candidate["filed"])
        cur_filed = date.fromisoformat(chosen["filed"])
        if cand_filed != cur_filed:
            return cand_filed < cur_filed
        cand_days, cur_days = _duration_days(candidate), _duration_days(chosen)
        if cand_days != cur_days:
            return cand_days < cur_days
        return str(candidate["end"]) > str(chosen["end"])


def _duration_days(entry: dict[str, Any]) -> int:
    """Days covered by a flow entry (instant concepts count as zero)."""
    if "start" not in entry:
        return 0
    return (date.fromisoformat(entry["end"]) - date.fromisoformat(entry["start"])).days
