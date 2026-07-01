"""Unit tests for the FactSet HTTP client (ticket: FactSet API client, Stage 2)."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from src.data.factset.client import (
    FactSetAPIError,
    FactSetAuthError,
    FactSetClient,
)


def _client(transport: Any, **kwargs: Any) -> FactSetClient:
    return FactSetClient("uid", "secret", transport=transport, sleeper=lambda _s: None, **kwargs)


def test_get_json_returns_parsed_body() -> None:
    def transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        return 200, json.dumps({"data": [1, 2]}).encode()

    assert _client(transport).get_json("/x", {"a": 1}) == {"data": [1, 2]}


def test_auth_header_is_http_basic() -> None:
    captured: dict[str, str] = {}

    def transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        captured.update(headers)
        return 200, b"{}"

    _client(transport).get_json("/x", {})
    assert captured["Authorization"] == "Basic " + base64.b64encode(b"uid:secret").decode()


def test_list_params_are_comma_joined() -> None:
    captured: dict[str, str] = {}

    def transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        captured["url"] = url
        return 200, b"{}"

    _client(transport).get_json("/prices", {"ids": ["AAPL-US", "MSFT-US"]})
    assert "ids=AAPL-US%2CMSFT-US" in captured["url"]


def test_retries_retryable_status_then_succeeds() -> None:
    calls: list[int] = []

    def transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        calls.append(1)
        return (503, b"busy") if len(calls) < 2 else (200, b'{"ok": true}')

    assert _client(transport, max_retries=3).get_json("/x", {}) == {"ok": True}
    assert len(calls) == 2


def test_exhausted_retries_raise_api_error() -> None:
    def transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        return 503, b"still busy"

    with pytest.raises(FactSetAPIError):
        _client(transport, max_retries=2).get_json("/x", {})


def test_auth_failure_raises_auth_error() -> None:
    def transport(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        return 401, b"unauthorized"

    with pytest.raises(FactSetAuthError):
        _client(transport).get_json("/x", {})
