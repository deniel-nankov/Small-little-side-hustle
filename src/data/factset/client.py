"""FactSet API connection manager (Stage 2).

A small HTTP client for the FactSet content APIs (base ``https://api.factset.com/content``).
Authenticates with HTTP Basic using the API-key credentials (``FACTSET_CLIENT_ID`` as the
username-serial, ``FACTSET_CLIENT_SECRET`` as the key), retries retryable statuses with
exponential backoff, and raises typed exceptions (never returns ``None``).

The actual network call is isolated behind an injectable ``transport`` so the client is
unit-testable with canned responses and no network. (OAuth2 client-credentials — FactSet's
signed-JWT flow — is a future auth option; Basic API-key auth is what our ``.env`` supports.)
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlencode

from src.monitoring.logger import get_logger

_log = get_logger(__name__)

#: Production content host.
BASE_URL = "https://api.factset.com/content"

#: HTTP statuses worth retrying (rate limit + transient server errors).
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 0.5

#: A transport does one HTTP GET: ``(url, headers) -> (status_code, body_bytes)``.
Transport = Callable[[str, dict[str, str]], tuple[int, bytes]]


class FactSetError(RuntimeError):
    """Base class for FactSet client errors."""


class FactSetAuthError(FactSetError):
    """Raised on 401/403 — credentials missing, invalid, or unentitled."""


class FactSetAPIError(FactSetError):
    """Raised on a non-retryable or exhausted-retry API error."""

    def __init__(self, status: int, body: bytes) -> None:
        """Capture the HTTP status and a truncated body for the error message."""
        self.status = status
        self.body = body.decode("utf-8", "replace")[:500]
        super().__init__(f"FactSet API returned {status}: {self.body}")


class FactSetClient:
    """Thin, retrying HTTP client for FactSet content APIs."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        base_url: str = BASE_URL,
        transport: Transport | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize the client.

        Args:
            client_id: FactSet API username-serial.
            client_secret: FactSet API key.
            base_url: Content host base URL.
            transport: Optional injected transport (for tests); defaults to urllib.
            max_retries: Total attempts for retryable statuses.
            backoff_base: Base seconds for exponential backoff (``base * 2**attempt``).
            sleeper: Sleep function (injectable so tests don't actually wait).
        """
        token = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self._auth_header = f"Basic {token}"
        self._base_url = base_url.rstrip("/")
        self._transport = transport or self._urllib_transport
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._sleep = sleeper

    @staticmethod
    def _urllib_transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        if not url.startswith("https://"):
            raise FactSetError(f"refusing non-https URL: {url}")
        request = urllib.request.Request(url, headers=headers)  # nosec B310 (https checked above)
        try:
            with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT) as response:  # nosec B310
                return int(response.status), response.read()
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read()

    def get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET ``path`` with query ``params`` and return the parsed JSON body.

        Args:
            path: API path beginning with ``/`` (e.g. ``/factset-global-prices/v1/prices``).
            params: Query parameters (lists are expanded, comma-joined per FactSet).

        Returns:
            The decoded JSON object.

        Raises:
            FactSetAuthError: on 401/403.
            FactSetAPIError: on other non-2xx (after exhausting retries).
        """
        query = urlencode(
            {k: (",".join(map(str, v)) if isinstance(v, list) else v) for k, v in params.items()}
        )
        url = f"{self._base_url}{path}?{query}"
        headers = {"Authorization": self._auth_header, "Accept": "application/json"}

        last_status = 0
        last_body = b""
        for attempt in range(self._max_retries):
            status, body = self._transport(url, headers)
            if status == 200:
                parsed: dict[str, Any] = json.loads(body)
                return parsed
            if status in (401, 403):
                raise FactSetAuthError(
                    f"FactSet auth failed ({status}) — check credentials/entitlement"
                )
            last_status, last_body = status, body
            if status in RETRYABLE_STATUS and attempt < self._max_retries - 1:
                delay = self._backoff_base * (2**attempt)
                _log.warning("factset.retry", status=status, attempt=attempt + 1, delay=delay)
                self._sleep(delay)
                continue
            break
        raise FactSetAPIError(last_status, last_body)
