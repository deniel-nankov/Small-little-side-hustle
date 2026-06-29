"""Structured logging for the whole platform.

Import :func:`get_logger` everywhere; never call the stdlib ``logging`` module or
``print`` directly (PRINCIPLES.md Rule 9, MONITORING.md). Output is human-readable in
development and single-line JSON in production, selected by ``APP_ENV``.

Example:
    >>> from src.monitoring.logger import get_logger
    >>> log = get_logger(__name__)
    >>> log.info("factset.pull.start", tickers=10, days=30)
"""

from __future__ import annotations

import functools
import logging
import sys
import time
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

import structlog
from config.settings import AppEnv, get_settings

_P = ParamSpec("_P")
_R = TypeVar("_R")

_configured = False


def configure_logging(level: str | None = None, app_env: AppEnv | None = None) -> None:
    """Configure structlog process-wide. Idempotent; safe to call repeatedly.

    Args:
        level: Log level name (e.g. ``"DEBUG"``). Defaults to ``settings.log_level``.
        app_env: Deployment profile selecting the renderer. Defaults to ``settings.app_env``.
    """
    global _configured
    cfg = get_settings()
    level_name = (level or cfg.log_level).upper()
    env = app_env or cfg.app_env
    min_level = logging.getLevelNamesMapping().get(level_name, logging.INFO)

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if env is AppEnv.production
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(min_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        # Disabled so re-configuring (e.g. in tests) always takes effect; negligible
        # overhead at our throughput.
        cache_logger_on_first_use=False,
    )
    _configured = True


def get_logger(name: str) -> Any:
    """Return a bound structured logger, configuring logging on first use.

    Args:
        name: Logger name, conventionally ``__name__`` of the calling module.

    Returns:
        A structlog bound logger with ``.debug/.info/.warning/.error/.critical``.
    """
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)


def log_function_call(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """Decorator: log function entry (``call.start``) and exit (``call.end``) at DEBUG.

    On exception, logs ``call.error`` at ERROR with the exception type and elapsed time,
    then re-raises — never swallows the error (PRINCIPLES.md Rule 2: no silent failures).

    Args:
        func: The function to wrap.

    Returns:
        The wrapped function with identical signature.
    """

    @functools.wraps(func)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        log = get_logger(func.__module__)
        log.debug("call.start", function=func.__qualname__)
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            log.error(
                "call.error",
                function=func.__qualname__,
                error=type(exc).__name__,
                message=str(exc),
                elapsed_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            raise
        log.debug(
            "call.end",
            function=func.__qualname__,
            elapsed_ms=round((time.perf_counter() - start) * 1000, 2),
        )
        return result

    return wrapper
