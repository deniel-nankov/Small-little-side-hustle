"""Portfolio risk statistics: VaR, CVaR, and scenario construction (Milestone 5).

Historical (non-parametric) VaR/CVaR from a set of scenario returns, plus a helper that
turns a price history into per-date scenario cross-sections. Pure standard library.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date

from src.data.contracts.schemas import PriceData

#: Default confidence level for VaR/CVaR.
CVAR_BETA = 0.95


def portfolio_scenario_returns(
    weights: Mapping[str, float], scenarios: Sequence[Mapping[str, float]]
) -> list[float]:
    """Portfolio return under each scenario.

    Args:
        weights: ``ticker`` -> weight.
        scenarios: Each a ``ticker`` -> return cross-section.

    Returns:
        One portfolio return per scenario (sum of weight*return over shared tickers).
    """
    return [sum(w * scenario.get(t, 0.0) for t, w in weights.items()) for scenario in scenarios]


def value_at_risk(returns: Sequence[float], beta: float = CVAR_BETA) -> float:
    """Historical Value-at-Risk (a non-negative loss magnitude) at level ``beta``.

    Args:
        returns: Scenario returns (gains positive, losses negative).
        beta: Confidence level, e.g. 0.95.

    Returns:
        The loss at the ``(1 - beta)`` worst quantile; 0.0 for empty input.
    """
    if not returns:
        return 0.0
    ordered = sorted(returns)
    index = min(len(ordered) - 1, max(0, math.ceil((1 - beta) * len(ordered)) - 1))
    return -ordered[index]


def conditional_value_at_risk(returns: Sequence[float], beta: float = CVAR_BETA) -> float:
    """Historical CVaR (expected shortfall): mean loss in the ``(1 - beta)`` worst tail.

    Args:
        returns: Scenario returns (gains positive, losses negative).
        beta: Confidence level, e.g. 0.95.

    Returns:
        The average loss (non-negative) in the worst tail; 0.0 for empty input.
    """
    if not returns:
        return 0.0
    ordered = sorted(returns)
    # epsilon guards against e.g. (1-0.8)*10 == 1.9999999999999996 -> floor 1 not 2
    tail_size = max(1, math.floor((1 - beta) * len(ordered) + 1e-9))
    return -statistics.fmean(ordered[:tail_size])


def build_scenarios(
    prices: Sequence[PriceData], as_of: date, lookback_days: int
) -> list[dict[str, float]]:
    """Build per-date scenario cross-sections of one-period returns ending on/before ``as_of``.

    Args:
        prices: Price bars for the universe.
        as_of: Only dates on or before this are used.
        lookback_days: Number of most-recent scenario dates to keep.

    Returns:
        A list of ``ticker`` -> one-period-return dicts, most recent ``lookback_days`` dates.
    """
    by_ticker: dict[str, list[PriceData]] = defaultdict(list)
    for bar in prices:
        if bar.date <= as_of:
            by_ticker[bar.ticker].append(bar)

    per_date: dict[date, dict[str, float]] = defaultdict(dict)
    for ticker, bars in by_ticker.items():
        bars.sort(key=lambda b: b.date)
        for i in range(1, len(bars)):
            per_date[bars[i].date][ticker] = (
                bars[i].adjusted_close / bars[i - 1].adjusted_close - 1.0
            )

    ordered_dates = sorted(per_date)[-lookback_days:]
    return [per_date[d] for d in ordered_dates]
