"""Unit tests for src/monitoring/logger.py."""

from __future__ import annotations

import pytest
import structlog
from config.settings import AppEnv
from src.monitoring.logger import configure_logging, get_logger, log_function_call


@pytest.fixture(autouse=True)
def _debug_logging() -> None:
    # Lower the level so DEBUG events from log_function_call are emitted/captured.
    configure_logging(level="DEBUG", app_env=AppEnv.development)


def test_get_logger_returns_usable_logger() -> None:
    log = get_logger("test")
    for method in ("debug", "info", "warning", "error", "critical"):
        assert hasattr(log, method)


def test_log_function_call_logs_start_and_end() -> None:
    @log_function_call
    def add(a: int, b: int) -> int:
        return a + b

    with structlog.testing.capture_logs() as caps:
        assert add(2, 3) == 5

    events = [c["event"] for c in caps]
    assert "call.start" in events
    assert "call.end" in events


def test_log_function_call_reraises_and_logs_error() -> None:
    @log_function_call
    def boom() -> None:
        raise ValueError("nope")

    with structlog.testing.capture_logs() as caps, pytest.raises(ValueError, match="nope"):
        boom()

    error_events = [c for c in caps if c["event"] == "call.error"]
    assert len(error_events) == 1
    assert error_events[0]["error"] == "ValueError"
