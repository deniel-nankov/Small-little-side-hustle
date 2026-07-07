"""Unit tests for the SEC EDGAR fundamentals client (ticket: public real-data sources).

EDGAR's companyfacts XBRL feed gives genuine point-in-time fundamentals for free: every
value carries the ``filed`` date of the filing that disclosed it. The client must:

* use the ORIGINAL (earliest-filed) value per concept/period — restatements must not
  rewrite history (no look-ahead);
* set ``report_date`` to the date on which ALL four concepts were knowable;
* pick the quarterly duration when a 10-Q reports both 3-month and year-to-date flows.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from src.data.public.client import PublicAPIError
from src.data.public.edgar import EdgarClient

_TICKERS_JSON = json.dumps(
    {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
).encode()


def _duration(concept_start: str, end: str, val: float, filed: str, fy: int, fp: str) -> dict:
    entry = {"start": concept_start, "end": end, "val": val, "filed": filed}
    return {**entry, "fy": fy, "fp": fp, "form": "10-Q"}


def _instant(end: str, val: float, filed: str, fy: int, fp: str) -> dict:
    return {"end": end, "val": val, "filed": filed, "fy": fy, "fp": fp, "form": "10-Q"}


def _facts_body() -> bytes:
    q2 = {"fy": 2026, "fp": "Q2"}
    facts = {
        "facts": {
            "us-gaap": {
                "Assets": {
                    "units": {
                        "USD": [
                            # Comparative prior fiscal-year-end balance FIRST in the list
                            # (as EDGAR serves it) — the current instant must still win.
                            _instant("2025-09-27", 340_000.0, "2026-05-02", **q2),
                            _instant("2026-03-28", 350_000.0, "2026-05-02", **q2),
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            # Quarterly (3-month) and YTD (6-month) durations for the SAME
                            # period — the client must pick the quarterly one.
                            _duration("2025-12-29", "2026-03-28", 24_000.0, "2026-05-02", **q2),
                            _duration("2025-09-29", "2026-03-28", 58_000.0, "2026-05-02", **q2),
                            # PRIOR-YEAR comparative quarter disclosed in the same 10-Q,
                            # same fy/fp tag, same duration length — the current period
                            # (latest end) must win, never the comparative.
                            _duration("2024-12-30", "2025-03-29", 19_000.0, "2026-05-02", **q2),
                            # A later restatement of the same quarter — must be IGNORED
                            # (original filing wins; no rewriting history).
                            {
                                "start": "2025-12-29",
                                "end": "2026-03-28",
                                "val": 99_999.0,
                                "filed": "2026-08-01",
                                "fy": 2026,
                                "fp": "Q2",
                                "form": "10-Q/A",
                            },
                        ]
                    }
                },
                "NetCashProvidedByUsedInOperatingActivities": {
                    "units": {
                        "USD": [
                            _duration("2025-12-29", "2026-03-28", 28_000.0, "2026-05-02", **q2),
                        ]
                    }
                },
                "Revenues": {
                    "units": {
                        "USD": [
                            _duration("2025-12-29", "2026-03-28", 95_000.0, "2026-05-02", **q2),
                        ]
                    }
                },
            }
        }
    }
    return json.dumps(facts).encode()


def _transport_factory():  # noqa: ANN202
    calls: list[tuple[str, dict[str, str]]] = []

    def transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        calls.append((url, headers))
        if "company_tickers" in url:
            return 200, _TICKERS_JSON
        return 200, _facts_body()

    return transport, calls


def test_builds_point_in_time_fundamentals() -> None:
    transport, _ = _transport_factory()
    client = EdgarClient("test-agent test@example.com", transport=transport)
    rows = client.get_fundamentals(["AAPL"], date(2026, 1, 1), date(2026, 6, 30))

    assert len(rows) == 1
    row = rows[0]
    assert row.ticker == "AAPL"
    assert row.report_date == date(2026, 5, 2)  # the FILED date, not the period end
    assert row.fiscal_year == 2026
    assert row.fiscal_quarter == 2
    assert row.total_assets == 350_000.0
    assert row.net_income == 24_000.0  # quarterly duration, original filing
    assert row.operating_cash_flow == 28_000.0
    assert row.revenue == 95_000.0
    assert row.is_point_in_time is True


def test_filters_by_filed_date_window() -> None:
    transport, _ = _transport_factory()
    client = EdgarClient("test-agent test@example.com", transport=transport)
    # Window ends before the 2026-05-02 filing -> nothing was knowable yet.
    assert client.get_fundamentals(["AAPL"], date(2026, 1, 1), date(2026, 4, 30)) == []


def test_unknown_ticker_raises() -> None:
    transport, _ = _transport_factory()
    client = EdgarClient("test-agent test@example.com", transport=transport)
    with pytest.raises(PublicAPIError, match="ZZZZ"):
        client.get_fundamentals(["ZZZZ"], date(2026, 1, 1), date(2026, 6, 30))


def test_sends_sec_user_agent_header() -> None:
    transport, calls = _transport_factory()
    client = EdgarClient("test-agent test@example.com", transport=transport)
    client.get_fundamentals(["AAPL"], date(2026, 1, 1), date(2026, 6, 30))
    assert all(h["User-Agent"] == "test-agent test@example.com" for _, h in calls)


def test_cik_is_zero_padded_in_facts_url() -> None:
    transport, calls = _transport_factory()
    client = EdgarClient("test-agent test@example.com", transport=transport)
    client.get_fundamentals(["AAPL"], date(2026, 1, 1), date(2026, 6, 30))
    facts_urls = [u for u, _ in calls if "companyfacts" in u]
    assert facts_urls == ["https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"]


def test_ticker_map_fetched_once_across_calls() -> None:
    transport, calls = _transport_factory()
    client = EdgarClient("test-agent test@example.com", transport=transport)
    client.get_fundamentals(["AAPL"], date(2026, 1, 1), date(2026, 6, 30))
    client.get_fundamentals(["AAPL"], date(2026, 1, 1), date(2026, 6, 30))
    assert sum("company_tickers" in u for u, _ in calls) == 1


def test_polite_delay_between_requests() -> None:
    # SEC fair-access: consecutive requests must be spaced out (rate-threshold 403s ban
    # the client for ~10 minutes). The sleeper is called between requests, never before
    # the first one.
    transport, calls = _transport_factory()
    naps: list[float] = []
    client = EdgarClient("test-agent test@example.com", transport=transport, sleeper=naps.append)
    client.get_fundamentals(["AAPL"], date(2026, 1, 1), date(2026, 6, 30))
    assert len(calls) == 2  # ticker map + companyfacts
    assert len(naps) == 1  # one polite nap between them
    assert all(n > 0 for n in naps)


def test_end_before_start_raises() -> None:
    transport, _ = _transport_factory()
    client = EdgarClient("test-agent test@example.com", transport=transport)
    with pytest.raises(ValueError, match="precedes"):
        client.get_fundamentals(["AAPL"], date(2026, 6, 30), date(2026, 1, 1))


def test_legacy_tag_does_not_shadow_recent_periods() -> None:
    # Real-world trap (seen live on AAPL): the higher-priority "Revenues" tag exists but
    # only with LEGACY entries; recent quarters live under RevenueFromContractWith
    # CustomerExcludingAssessedTax. Tag priority must be resolved per period, not globally.
    body = json.loads(_facts_body())
    gaap = body["facts"]["us-gaap"]
    recent_revenue = gaap.pop("Revenues")  # the fixture's recent Q2 revenue entry
    gaap["RevenueFromContractWithCustomerExcludingAssessedTax"] = recent_revenue
    gaap["Revenues"] = {  # higher-priority tag exists, but with a LEGACY period only
        "units": {
            "USD": [_duration("2017-10-01", "2017-12-30", 88_000.0, "2018-02-02", 2018, "Q1")]
        }
    }

    def transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        if "company_tickers" in url:
            return 200, _TICKERS_JSON
        return 200, json.dumps(body).encode()

    client = EdgarClient("test-agent test@example.com", transport=transport)
    rows = client.get_fundamentals(["AAPL"], date(2026, 1, 1), date(2026, 6, 30))
    assert len(rows) == 1
    assert rows[0].revenue == 95_000.0  # pulled from the newer tag despite legacy Revenues


def test_incomplete_period_is_skipped() -> None:
    # Remove Revenues entirely: the period lacks one of the four concepts -> no row.
    body = json.loads(_facts_body())
    del body["facts"]["us-gaap"]["Revenues"]

    def transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        if "company_tickers" in url:
            return 200, _TICKERS_JSON
        return 200, json.dumps(body).encode()

    client = EdgarClient("test-agent test@example.com", transport=transport)
    assert client.get_fundamentals(["AAPL"], date(2026, 1, 1), date(2026, 6, 30)) == []
