"""Regime-stability test (Milestone 3).

Validation test #5. A signal that is really a hidden bet on one market environment will
have IC in that environment and noise elsewhere. We label each date with up to two
overlapping regimes — a direction (bull/bear) and a volatility state (high_vol/low_vol),
derived from an equal-weight market proxy — then require positive IC in at least 3 of the 4
regimes.

The regimes are overlapping labels, not a 2x2 partition: each date carries one direction
label and one volatility label, so a single date's IC contributes to two buckets.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from src.data.contracts.schemas import PriceData, SignalScore
from src.signals.validation.ic_calculator import MIN_CROSS_SECTION_SIZE, daily_ics

#: The four regime labels.
REGIMES: tuple[str, ...] = ("bull", "bear", "high_vol", "low_vol")

#: Trailing window (observations) for the trend and volatility classifiers.
TREND_WINDOW = 21
VOL_WINDOW = 21

#: Minimum number of the four regimes that must show positive IC.
MIN_REGIMES_POSITIVE = 3


class RegimeTestResult(BaseModel):
    """Outcome of the regime-stability test."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    by_regime: dict[str, float]  # regime -> mean IC (only regimes with data)
    n_positive: int = Field(ge=0)
    min_required: int = Field(ge=0)
    passed: bool


def _market_returns(prices: Sequence[PriceData]) -> dict[date, float]:
    """Equal-weight cross-sectional mean of one-day returns, per date."""
    by_ticker: dict[str, list[PriceData]] = defaultdict(list)
    for bar in prices:
        by_ticker[bar.ticker].append(bar)
    per_date: dict[date, list[float]] = defaultdict(list)
    for bars in by_ticker.values():
        bars.sort(key=lambda b: b.date)
        for i in range(1, len(bars)):
            ret = bars[i].adjusted_close / bars[i - 1].adjusted_close - 1.0
            per_date[bars[i].date].append(ret)
    return {d: statistics.fmean(rs) for d, rs in per_date.items()}


def classify_regimes(
    prices: Sequence[PriceData],
    trend_window: int = TREND_WINDOW,
    vol_window: int = VOL_WINDOW,
) -> dict[date, frozenset[str]]:
    """Label each date with a direction and (when computable) a volatility regime.

    Args:
        prices: Price bars for the universe.
        trend_window: Trailing window for the bull/bear classifier.
        vol_window: Trailing window for the high/low-vol classifier.

    Returns:
        Mapping of date to its set of regime labels (1 or 2 labels per date).
    """
    market = _market_returns(prices)
    ordered = sorted(market)
    trailing_vol: dict[date, float] = {}
    trend_up: dict[date, bool] = {}
    for i, day in enumerate(ordered):
        trend_slice = [market[d] for d in ordered[max(0, i - trend_window + 1) : i + 1]]
        trend_up[day] = statistics.fmean(trend_slice) >= 0
        vol_slice = [market[d] for d in ordered[max(0, i - vol_window + 1) : i + 1]]
        if len(vol_slice) >= 2:
            trailing_vol[day] = statistics.pstdev(vol_slice)

    median_vol = statistics.median(trailing_vol.values()) if trailing_vol else None
    labels: dict[date, frozenset[str]] = {}
    for day in ordered:
        tags = {"bull" if trend_up[day] else "bear"}
        if median_vol is not None and day in trailing_vol:
            tags.add("high_vol" if trailing_vol[day] >= median_vol else "low_vol")
        labels[day] = frozenset(tags)
    return labels


def regime_test(
    scores: Sequence[SignalScore],
    forward_returns: Mapping[tuple[str, date], float],
    prices: Sequence[PriceData],
    min_regimes_positive: int = MIN_REGIMES_POSITIVE,
    min_cross_section: int = MIN_CROSS_SECTION_SIZE,
) -> RegimeTestResult:
    """Require positive IC in at least ``min_regimes_positive`` of the four regimes.

    Args:
        scores: Signal scores across tickers and dates.
        forward_returns: ``(ticker, date)`` -> forward return (same horizon as the main IC).
        prices: Price bars used to classify regimes.
        min_regimes_positive: Threshold count of regimes with positive IC.
        min_cross_section: Minimum names required to score a date.

    Returns:
        A :class:`RegimeTestResult`.

    Raises:
        ValueError: if no date had a computable IC.
    """
    series = daily_ics(scores, forward_returns, min_cross_section)
    if not series:
        raise ValueError("no date had a computable IC")
    regimes = classify_regimes(prices)

    buckets: dict[str, list[float]] = {r: [] for r in REGIMES}
    for day, ic in series:
        for label in regimes.get(day, frozenset()):
            buckets[label].append(ic)

    by_regime = {r: statistics.fmean(vals) for r, vals in buckets.items() if vals}
    n_positive = sum(1 for r in REGIMES if by_regime.get(r, 0.0) > 0)
    return RegimeTestResult(
        by_regime=by_regime,
        n_positive=n_positive,
        min_required=min_regimes_positive,
        passed=n_positive >= min_regimes_positive,
    )
