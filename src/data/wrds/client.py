"""WRDS REST API client (#55).

Thin, paginating client over ``https://wrds-api.wharton.upenn.edu/data/{library}.{table}/``.
The API has four behaviors, all verified live on 2026-08-27, that silently corrupt data
if unhandled — this client exists to neutralize every one of them:

1. **``count`` is a Postgres planner ESTIMATE and is wrong.** A query that returned
   11,105 correct rows reported ``count: 3508``. Pagination therefore NEVER consults
   ``count``: it follows ``next`` and stops when a page comes back empty.
2. **Unknown query params are silently ignored** — a typo'd filter name returns the
   FULL unfiltered table with HTTP 200. Every response is therefore VERIFIED against
   the requested filters, and a mismatch raises rather than returning foreign data.
3. **No range operators.** ``date__gte`` is not supported and yields
   ``count:1, results:[]``. Such filters are rejected upfront with a clear message;
   callers filter by entity key and slice dates client-side.
4. **``next`` links come back as plain ``http://``** even for an https request —
   they are upgraded before use so the token never crosses the wire in plaintext.

Rate limits: WRDS tolerates modest concurrency; huge unfiltered tables 500 on the COUNT
query, so always filter by an entity key first.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from src.data.http import HttpClient, Transport
from src.monitoring.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

_log = get_logger(__name__)

#: Production host. HTTPS always — the token is equivalent to a username/password.
WRDS_BASE = "https://wrds-api.wharton.upenn.edu/data"

#: Rows per request. The API honors large pages; 20k keeps payloads manageable.
DEFAULT_PAGE_SIZE = 20_000

#: Polite spacing between requests (shared academic infrastructure).
POLITE_INTERVAL_S = 0.2

#: Hard ceiling so a mistyped call cannot try to pull a 235M-row table into memory.
MAX_ROWS_CEILING = 5_000_000


def _upgrade_scheme(url: str) -> str:
    """Upgrade a plain-http URL to https (anchored — never rewrites the query string)."""
    return f"https://{url[len('http://') :]}" if url.startswith("http://") else url


def _values_match(actual: object, wanted: object) -> bool:
    """Compare a returned cell against a requested filter value, tolerantly.

    WRDS serializes inconsistently across libraries: Compustat ``gvkey`` comes back
    zero-padded (``"001690"`` for ``1690``), numerics arrive as ``"14593.0"`` or
    ``14593``, and dates as ISO strings. A false mismatch here would wrongly reject a
    perfectly good response, so equality is checked by string, then numerically.
    """
    a, w = str(actual).strip(), str(wanted).strip()
    if a == w:
        return True
    try:
        return float(a) == float(w)
    except ValueError:
        return a.lstrip("0") == w.lstrip("0") and bool(a.lstrip("0"))


class WRDSClient:
    """Paginating REST client for WRDS datasets."""

    def __init__(
        self,
        token: str,
        *,
        transport: Transport | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize the client.

        Args:
            token: WRDS API authorization token (from ``WRDS_API_TOKEN``).
            transport: Optional injected transport (for tests); defaults to urllib.
            page_size: Rows requested per page.
            sleeper: Sleep function for retry/politeness (injectable for tests).
        """
        self._http = HttpClient(
            {"Authorization": f"Token {token}", "Accept": "application/json"},
            transport=transport,
            min_interval=POLITE_INTERVAL_S,
            sleeper=sleeper,
        )
        self._page_size = page_size

    def get_rows(
        self,
        table: str,
        *,
        filters: Mapping[str, object] | None = None,
        ordering: str | None = None,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch rows from ``table``, paginating until the data is exhausted.

        Args:
            table: Qualified dataset name, e.g. ``"crsp.dsf"``.
            filters: Column equality filters, e.g. ``{"permno": 14593}``. Range
                operators are NOT supported by the API and are rejected here.
            ordering: Optional sort field, e.g. ``"-date"`` for newest first.
            max_rows: Stop after this many rows (defaults to ``MAX_ROWS_CEILING``).

        Returns:
            The rows as dicts, in API order.

        Raises:
            ValueError: on a malformed table name, a range-operator filter, or if the
                API silently ignored a filter (returned rows that do not match it).
            DataAPIError: on HTTP failure after retries.
        """
        if "." not in table:
            raise ValueError(f"table must be 'library.table', got {table!r}")
        filters = dict(filters or {})
        for name in filters:
            if "__" in name:
                raise ValueError(
                    f"filter {name!r} uses a range operator; the WRDS API does not "
                    "support them (it silently returns an empty page). Filter by an "
                    "entity key and slice the range client-side."
                )

        cap = MAX_ROWS_CEILING if max_rows is None else min(max_rows, MAX_ROWS_CEILING)
        params: dict[str, object] = {"limit": min(self._page_size, cap), **filters}
        if ordering is not None:
            params["ordering"] = ordering
        url: str | None = f"{WRDS_BASE}/{table}/?{urlencode(params)}"

        rows: list[dict[str, Any]] = []
        pages = 0
        truncated = False
        while url is not None and len(rows) < cap:
            payload = json.loads(self._http.get_bytes(url))
            page = payload.get("results") or []
            pages += 1
            if not page:
                break  # authoritative end-of-data; `count` is an estimate and unusable
            # Verify the FIRST page before buffering more: when the API ignores a filter
            # it returns the whole table, so checking only at the end would stream
            # millions of unrelated rows before failing.
            self._verify_filters(table, page, filters)
            rows.extend(page)
            next_url = payload.get("next")
            if len(rows) >= cap:
                truncated = next_url is not None or len(rows) > cap
                break
            # WRDS returns http:// next-links even for https requests; never downgrade.
            url = _upgrade_scheme(next_url) if next_url else None

        rows = rows[:cap]
        if truncated:
            _log.warning(
                "wrds.truncated",
                table=table,
                rows=len(rows),
                max_rows=cap,
                detail="more data exists upstream; result is a PREFIX, not the full series",
            )
        _log.info("wrds.fetched", table=table, rows=len(rows), pages=pages, filters=filters)
        return rows

    @staticmethod
    def _verify_filters(
        table: str, rows: list[dict[str, Any]], filters: Mapping[str, object]
    ) -> None:
        """Fail loudly if the API ignored a filter and returned unrelated rows.

        The API answers 200 with the FULL table when a filter name is not a real column,
        so a typo would otherwise pass 107M unrelated rows off as one ticker's history.
        """
        if not rows or not filters:
            return
        sample = rows[0]
        for name, wanted in filters.items():
            if name in ("limit", "ordering"):
                continue
            if name not in sample:
                raise ValueError(
                    f"WRDS did not honor filter {name!r} on {table}: the column is absent "
                    "from the response (likely not a real column — the API ignores "
                    "unknown params and returns the whole table)"
                )
            mismatched = [r for r in rows if not _values_match(r.get(name), wanted)]
            if mismatched:
                raise ValueError(
                    f"WRDS did not honor filter {name}={wanted!r} on {table}: "
                    f"{len(mismatched)} of {len(rows)} rows disagree "
                    f"(first offender {name}={mismatched[0].get(name)!r})"
                )
