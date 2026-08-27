"""Unit tests for the WRDS REST client (#55).

Every test here encodes a trap verified against the LIVE WRDS API on 2026-08-27. These
are not hypotheticals — each one silently corrupts data if unhandled:

* ``count`` is a Postgres planner ESTIMATE and is wrong (live: reported 3,508 for a
  query that returned 11,105 correct rows). Paginating on it truncates ~70% of the data.
* Unknown query params are SILENTLY IGNORED — a typo'd filter returns the FULL
  unfiltered table with no error.
* Range operators (``date__gte``) are not supported and yield ``count:1, results:[]``.
* ``next`` links come back as **http://** even on an https request.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from src.data.http import DataAPIError
from src.data.wrds import client as client_module
from src.data.wrds.client import WRDS_BASE, WRDSClient

_TOKEN = "test-token-abc"  # noqa: S105 (fake token for tests)


def _page(results: list[dict[str, Any]], *, count: int, next_url: str | None) -> bytes:
    body = {"count": count, "next": next_url, "previous": None, "results": results}
    return json.dumps(body).encode()


def _rows(n: int, start: int = 0, permno: int = 14593) -> list[dict[str, Any]]:
    return [
        {"permno": permno, "date": f"2020-01-{i + 1:02d}", "prc": 100.0 + i}
        for i in range(start, start + n)
    ]


def _canned(pages: list[bytes]):  # noqa: ANN202
    calls: list[tuple[str, dict[str, str]]] = []

    def transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        calls.append((url, headers))
        return 200, pages[min(len(calls) - 1, len(pages) - 1)]

    return transport, calls


# --------------------------------------------------------------------------- auth + URL


def test_sends_token_auth_header() -> None:
    transport, calls = _canned([_page(_rows(1), count=1, next_url=None)])
    WRDSClient(_TOKEN, transport=transport).get_rows("crsp.dsf", filters={"permno": 14593})
    assert calls[0][1]["Authorization"] == f"Token {_TOKEN}"


def test_uses_https_base() -> None:
    transport, calls = _canned([_page(_rows(1), count=1, next_url=None)])
    WRDSClient(_TOKEN, transport=transport).get_rows("crsp.dsf", filters={"permno": 14593})
    assert calls[0][0].startswith(f"{WRDS_BASE}/crsp.dsf/")
    assert WRDS_BASE.startswith("https://")  # token is a credential; never plaintext


def test_filters_and_ordering_are_encoded_in_the_url() -> None:
    transport, calls = _canned([_page(_rows(1), count=1, next_url=None)])
    WRDSClient(_TOKEN, transport=transport).get_rows(
        "crsp.dsf", filters={"permno": 14593}, ordering="-date"
    )
    url = calls[0][0]
    assert "permno=14593" in url
    assert "ordering=-date" in url


# ------------------------------------------------- TRAP 1: `count` is a lying estimate


def test_pagination_ignores_the_lying_count() -> None:
    # Live behavior: count said 3,508 while 11,105 real rows existed. Trusting count
    # would silently drop most of the data, so the client must page until exhausted.
    page1 = _page(_rows(3), count=3508, next_url=f"{WRDS_BASE}/crsp.dsf/?offset=3")
    page2 = _page(_rows(2, start=3), count=3508, next_url=None)
    transport, _ = _canned([page1, page2])
    rows = WRDSClient(_TOKEN, transport=transport).get_rows("crsp.dsf", filters={"permno": 14593})
    assert len(rows) == 5  # NOT 3508, and not truncated to page 1


def test_stops_on_empty_results_even_if_next_is_set() -> None:
    page1 = _page(_rows(2), count=99, next_url=f"{WRDS_BASE}/crsp.dsf/?offset=2")
    page2 = _page([], count=99, next_url=f"{WRDS_BASE}/crsp.dsf/?offset=4")  # empty but "more"
    transport, calls = _canned([page1, page2])
    rows = WRDSClient(_TOKEN, transport=transport).get_rows("crsp.dsf", filters={"permno": 14593})
    assert len(rows) == 2
    assert len(calls) == 2  # stopped; did not loop forever


# ---------------------------------------------------- TRAP 2: `next` comes back as http


def test_next_link_is_upgraded_to_https() -> None:
    insecure = "http://wrds-api.wharton.upenn.edu/data/crsp.dsf/?limit=2&offset=2"
    page1 = _page(_rows(2), count=4, next_url=insecure)
    page2 = _page(_rows(2, start=2), count=4, next_url=None)
    transport, calls = _canned([page1, page2])
    WRDSClient(_TOKEN, transport=transport).get_rows("crsp.dsf", filters={"permno": 14593})
    assert calls[1][0].startswith("https://")  # never send the token in plaintext


# --------------------------------------- TRAP 3: silently-ignored filters must be caught


def test_raises_when_api_silently_ignores_a_filter() -> None:
    # A typo'd filter name returns the FULL table. The rows won't match what we asked
    # for, so the client verifies the response and fails loudly instead of returning
    # someone else's data as if it were ours.
    wrong = [{"permno": 99999, "date": "2020-01-01", "prc": 1.0}]
    transport, _ = _canned([_page(wrong, count=1, next_url=None)])
    with pytest.raises(ValueError, match="did not honor"):
        WRDSClient(_TOKEN, transport=transport).get_rows("crsp.dsf", filters={"permno": 14593})


def test_raises_when_filter_column_absent_from_rows() -> None:
    rows = [{"date": "2020-01-01", "prc": 1.0}]  # no `permno` key at all
    transport, _ = _canned([_page(rows, count=1, next_url=None)])
    with pytest.raises(ValueError, match="did not honor"):
        WRDSClient(_TOKEN, transport=transport).get_rows("crsp.dsf", filters={"permno": 14593})


def test_filter_verification_compares_as_strings() -> None:
    # The API returns numbers as strings inconsistently; 14593 == "14593" must pass.
    rows = [{"permno": "14593", "date": "2020-01-01", "prc": 1.0}]
    transport, _ = _canned([_page(rows, count=1, next_url=None)])
    got = WRDSClient(_TOKEN, transport=transport).get_rows("crsp.dsf", filters={"permno": 14593})
    assert len(got) == 1


# ------------------------------------------------- TRAP 4: range operators don't exist


@pytest.mark.parametrize("bad", ["date__gte", "date__lte", "date__gt"])
def test_range_operator_filters_are_rejected_upfront(bad: str) -> None:
    transport, _ = _canned([_page([], count=1, next_url=None)])
    with pytest.raises(ValueError, match="range operator"):
        WRDSClient(_TOKEN, transport=transport).get_rows("crsp.dsf", filters={bad: "2020-01-01"})


# ------------------------------------------------------------------- limits and errors


def test_max_rows_caps_the_pull() -> None:
    page = _page(_rows(50), count=10_000, next_url=f"{WRDS_BASE}/crsp.dsf/?offset=50")
    transport, calls = _canned([page])
    rows = WRDSClient(_TOKEN, transport=transport).get_rows(
        "crsp.dsf", filters={"permno": 14593}, max_rows=60
    )
    assert len(rows) == 60
    assert len(calls) == 2  # stopped as soon as the cap was reached


def test_page_size_is_clamped_to_the_remaining_budget() -> None:
    # Asking for 60 rows must not request 20,000-row pages off the wire.
    transport, calls = _canned([_page(_rows(60), count=99, next_url=None)])
    WRDSClient(_TOKEN, transport=transport).get_rows(
        "crsp.dsf", filters={"permno": 14593}, max_rows=60
    )
    assert "limit=60" in calls[0][0]


def test_bad_filter_fails_on_the_first_page_not_after_millions_of_rows() -> None:
    # An ignored filter makes WRDS stream the WHOLE table; verification must fire on
    # page 1 rather than buffering to the ceiling first.
    wrong = _page(_rows(50, permno=99999), count=10**7, next_url=f"{WRDS_BASE}/crsp.dsf/?offset=50")
    transport, calls = _canned([wrong])
    with pytest.raises(ValueError, match="did not honor"):
        WRDSClient(_TOKEN, transport=transport).get_rows("crsp.dsf", filters={"permno": 14593})
    assert len(calls) == 1  # bailed immediately


def test_truncation_is_flagged_not_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        client_module._log, "warning", lambda event, **kw: warnings.append(event)
    )
    page = _page(_rows(50), count=10_000, next_url=f"{WRDS_BASE}/crsp.dsf/?offset=50")
    transport, _ = _canned([page])
    WRDSClient(_TOKEN, transport=transport).get_rows(
        "crsp.dsf", filters={"permno": 14593}, max_rows=60
    )
    # A prefix must never look like a full series to the caller.
    assert "wrds.truncated" in warnings


def test_complete_pull_is_not_flagged_as_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        client_module._log, "warning", lambda event, **kw: warnings.append(event)
    )
    transport, _ = _canned([_page(_rows(5), count=99, next_url=None)])
    WRDSClient(_TOKEN, transport=transport).get_rows("crsp.dsf", filters={"permno": 14593})
    assert warnings == []


@pytest.mark.parametrize(
    ("returned", "requested"),
    [("001690", 1690), (14593.0, 14593), ("14593", 14593), (1690, "001690")],
)
def test_filter_verification_tolerates_wrds_serialization_quirks(
    returned: object, requested: object
) -> None:
    # Compustat zero-pads gvkey; numerics arrive as floats or strings. A false mismatch
    # here would reject a perfectly good response.
    rows = [{"gvkey": returned, "datadate": "2020-01-01"}]
    transport, _ = _canned([_page(rows, count=1, next_url=None)])
    got = WRDSClient(_TOKEN, transport=transport).get_rows(
        "comp.fundq", filters={"gvkey": requested}
    )
    assert len(got) == 1


def test_https_next_link_with_embedded_http_value_is_not_corrupted() -> None:
    # An anchored upgrade only: a query value containing "http://" must survive intact.
    tricky = f"{WRDS_BASE}/crsp.dsf/?limit=2&offset=2&note=http://x"
    page1 = _page(_rows(2), count=4, next_url=tricky)
    page2 = _page(_rows(2, start=2), count=4, next_url=None)
    transport, calls = _canned([page1, page2])
    WRDSClient(_TOKEN, transport=transport).get_rows("crsp.dsf", filters={"permno": 14593})
    assert calls[1][0] == tricky  # unchanged: already https, embedded value preserved


def test_auth_failure_raises() -> None:
    def transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        return 403, b"forbidden"

    with pytest.raises(DataAPIError, match="403"):
        WRDSClient(_TOKEN, transport=transport).get_rows("crsp.dsf", filters={"permno": 1})


def test_transient_500_is_retried() -> None:
    # Live: unfiltered/huge tables 500 on the COUNT query under concurrency.
    responses = [(500, b"boom"), (200, _page(_rows(1), count=1, next_url=None))]
    naps: list[float] = []

    def transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        return responses.pop(0)

    client = WRDSClient(_TOKEN, transport=transport, sleeper=naps.append)
    assert len(client.get_rows("crsp.dsf", filters={"permno": 14593})) == 1
    assert len(naps) >= 1


def test_empty_table_returns_empty_list() -> None:
    transport, _ = _canned([_page([], count=0, next_url=None)])
    assert WRDSClient(_TOKEN, transport=transport).get_rows("crsp.dsf") == []


def test_rejects_malformed_table_name() -> None:
    transport, _ = _canned([_page([], count=0, next_url=None)])
    with pytest.raises(ValueError, match="library.table"):
        WRDSClient(_TOKEN, transport=transport).get_rows("crspdsf")
