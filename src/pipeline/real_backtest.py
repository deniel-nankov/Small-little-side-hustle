"""End-to-end fundamental-signal backtest on any DataSource (fixture, public, factset).

The first pipeline able to produce a REAL backtest number: point-in-time fundamentals →
:func:`compute_fundamental_factors` per score date → the 7-test validation suite →
persisted, hash-sidecarred :class:`BacktestResult`.

Leakage defenses, in order:

1. The source is wrapped in :class:`PITDataSource` pinned at the backtest ``end`` — the
   pipeline physically cannot fetch anything knowable after the window.
2. Per score date ``d``, fundamentals are pre-filtered with :func:`as_of` AND
   :func:`compute_fundamental_factors` re-filters on ``report_date <= d`` internally
   (and raises on any non point-in-time record).
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from src.data.contracts.schemas import BacktestResult
from src.monitoring.logger import get_logger
from src.signals.construction.fundamental_factors import (
    SIGNAL_NAME,
    compute_fundamental_factors,
)
from src.signals.validation.backtest_runner import run_backtest
from src.utils.integrity import write_with_sidecar
from src.utils.pit import PITDataSource, as_of

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date
    from pathlib import Path

    from src.data.contracts.schemas import SignalScore
    from src.data.source.base import DataSource
    from src.monitoring.audit import AuditLog

_log = get_logger(__name__)

#: Fundamentals lookback before the first score date: ~6 quarters, so revenue
#: acceleration (needs 3 fiscal periods) is computable from day one.
DEFAULT_LOOKBACK_DAYS = 550

#: Compute scores every N-th trading day (fundamentals move quarterly; weekly is plenty).
DEFAULT_SCORE_EVERY = 5


def run_fundamental_backtest(
    source: DataSource,
    tickers: Sequence[str],
    start: date,
    end: date,
    *,
    score_every: int = DEFAULT_SCORE_EVERY,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    n_trials: int = 1,
    audit: AuditLog | None = None,
    out_dir: Path | None = None,
) -> BacktestResult:
    """Backtest the fundamental-factor signal over ``[start, end]`` on ``source``.

    Args:
        source: Any data source (``FixtureSource``, ``PublicSource``, ``FactSetSource``);
            it is wrapped in a :class:`PITDataSource` pinned at ``end``.
        tickers: Universe to score (cross-sectional signal — 8+ tickers recommended).
        start: First score date (inclusive).
        end: Last data date (inclusive); nothing after it can enter the backtest.
        score_every: Compute scores every N-th trading day.
        lookback_days: How far before ``start`` to fetch fundamentals (trailing periods).
        n_trials: How many candidate signals were tried (multiple-testing p-value guard).
        audit: Optional tamper-evident audit log (PIT clamps + verdict are recorded).
        out_dir: Optional directory; when set, the result JSON is written there
            atomically with a SHA-256 sidecar.

    Returns:
        The :class:`BacktestResult` from the 7-test validation suite.

    Raises:
        ValueError: if ``end`` precedes ``start``, or no scores are computable.
    """
    if end < start:
        raise ValueError(f"end ({end}) precedes start ({start})")

    pit = PITDataSource(source, as_of=end, audit=audit)
    prices = pit.get_prices(tickers, start, end)
    fundamentals = pit.get_fundamentals(tickers, start - timedelta(days=lookback_days), end)
    _log.info(
        "pipeline.data_loaded",
        source=pit.name,
        tickers=len(tickers),
        price_bars=len(prices),
        fundamental_rows=len(fundamentals),
    )

    trading_days = sorted({bar.date for bar in prices})
    score_dates = trading_days[:: max(1, score_every)]
    scores: list[SignalScore] = []
    for day in score_dates:
        scores.extend(compute_fundamental_factors(as_of(fundamentals, day), as_of=day))
    if not scores:
        raise ValueError("no scores computable — check ticker universe / data coverage")
    _log.info("pipeline.scores_computed", score_dates=len(score_dates), scores=len(scores))

    result = run_backtest(scores, prices, n_trials=n_trials, audit=audit)

    if out_dir is not None:
        artifact = out_dir / f"{SIGNAL_NAME}_{start.isoformat()}_{end.isoformat()}.json"
        digest = write_with_sidecar(artifact, result.model_dump_json(indent=2).encode("utf-8"))
        _log.info("pipeline.artifact_written", path=str(artifact), sha256=digest)

    _log.info(
        "pipeline.backtest_done",
        signal=result.signal_name,
        passed=result.passed_validation,
        mean_ic=round(result.mean_ic, 4),
        sharpe=round(result.sharpe_ratio, 2),
    )
    return result
