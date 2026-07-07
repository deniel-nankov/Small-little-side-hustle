"""Shared HTTP plumbing for the free public data sources (EDGAR, Stooq).

Mirrors the FactSet client's discipline: https-only, retry with exponential backoff on
transient statuses, typed errors, and an injectable ``transport`` so every caller is
unit-testable with canned responses and zero network.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Callable

from src.monitoring.logger import get_logger

_log = get_logger(__name__)

#: HTTP statuses worth retrying (rate limit + transient server errors).
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 0.5

#: A transport does one HTTP GET: ``(url, headers) -> (status_code, body_bytes)``.
Transport = Callable[[str, dict[str, str]], tuple[int, bytes]]


class PublicAPIError(RuntimeError):
    """Raised on a non-retryable or exhausted-retry public-API error."""

    def __init__(self, status: int, body: bytes) -> None:
        """Capture the HTTP status and a truncated body for the error message."""
        self.status = status
        self.body = body.decode("utf-8", "replace")[:500]
        super().__init__(f"public API returned {status}: {self.body}")


class HttpClient:
    """Thin, retrying, GET-only HTTP client for the free public data feeds."""

    def __init__(
        self,
        headers: dict[str, str],
        *,
        transport: Transport | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        min_interval: float = 0.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize the client.

        Args:
            headers: Headers sent with every request (e.g. the SEC ``User-Agent``).
            transport: Optional injected transport (for tests); defaults to urllib.
            max_retries: Total attempts for retryable statuses.
            backoff_base: Base seconds for exponential backoff (``base * 2**attempt``).
            min_interval: Polite delay (seconds) slept before every request after the
                first — for feeds with fair-access rate rules (SEC EDGAR).
            sleeper: Sleep function (injectable so tests don't actually wait).
        """
        self._headers = headers
        self._transport = transport or self._urllib_transport
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._min_interval = min_interval
        self._made_request = False
        self._sleep = sleeper

    @staticmethod
    def _urllib_transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        if not url.startswith("https://"):
            raise PublicAPIError(0, f"refusing non-https URL: {url}".encode())
        request = urllib.request.Request(url, headers=headers)  # nosec B310 (https checked above)
        try:
            with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT) as response:  # nosec B310
                return int(response.status), response.read()
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read()

    def get_bytes(self, url: str) -> bytes:
        """GET ``url`` and return the response body.

        Args:
            url: Fully-formed https URL.

        Returns:
            The raw response body on HTTP 200.

        Raises:
            PublicAPIError: on non-2xx (after exhausting retries on transient statuses).
        """
        if self._made_request and self._min_interval > 0:
            self._sleep(self._min_interval)
        self._made_request = True

        last_status = 0
        last_body = b""
        for attempt in range(self._max_retries):
            status, body = self._transport(url, self._headers)
            if status == 200:
                return body
            last_status, last_body = status, body
            if status in RETRYABLE_STATUS and attempt < self._max_retries - 1:
                delay = self._backoff_base * (2**attempt)
                _log.warning("public.retry", status=status, attempt=attempt + 1, delay=delay)
                self._sleep(delay)
                continue
            break
        raise PublicAPIError(last_status, last_body)
