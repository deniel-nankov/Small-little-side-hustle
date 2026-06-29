"""Information Coefficient toolkit; the judge of every signal (Milestone 3).

Computes the Information Coefficient (Spearman rank correlation of signal score vs. forward
return) and its summary statistics: mean IC, IC std, ICIR, t-statistic, p-value,
positive-IC ratio, and a per-regime breakdown.

Implemented in pure Python (standard library only) so the validation core runs identically
in every environment with no native-wheel dependency, and every statistic can be checked
against hand-computed ground truth. See docs/TESTING.md for the acceptance thresholds.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from src.data.contracts.schemas import PriceData, SignalScore
from src.monitoring.logger import get_logger

_log = get_logger(__name__)

#: Minimum number of names required to compute a cross-sectional IC for one date.
MIN_CROSS_SECTION_SIZE = 5

#: Default forward-return horizon, in trading observations (~one month).
DEFAULT_FORWARD_HORIZON_DAYS = 21


class ICReport(BaseModel):
    """Summary statistics of a signal's Information Coefficient over time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mean_ic: float
    ic_std: float = Field(ge=0)
    icir: float
    t_statistic: float
    p_value: float = Field(ge=0, le=1)
    positive_ic_ratio: float = Field(ge=0, le=1)
    n_periods: int = Field(ge=0)
    by_regime: dict[str, float] = Field(default_factory=dict)


# --------------------------------------------------------------------------- statistics
def _average_ranks(values: Sequence[float]) -> list[float]:
    """Return 1-based ranks of ``values``, averaging ties.

    Args:
        values: The values to rank.

    Returns:
        Ranks aligned to the input order; tied values share their average rank.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average_rank = (i + j) / 2 + 1  # mean of 0-based positions i..j, shifted to 1-based
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1
    return ranks


def _pearson(x: Sequence[float], y: Sequence[float]) -> float:
    """Pearson correlation of two equal-length sequences.

    Raises:
        ValueError: if lengths differ, fewer than two points, or either has zero variance.
    """
    if len(x) != len(y):
        raise ValueError(f"length mismatch: {len(x)} != {len(y)}")
    if len(x) < 2:
        raise ValueError("need at least two observations")
    mean_x = statistics.fmean(x)
    mean_y = statistics.fmean(y)
    sxx = sum((a - mean_x) ** 2 for a in x)
    syy = sum((b - mean_y) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        raise ValueError("zero variance in input")
    sxy = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y, strict=True))
    return sxy / math.sqrt(sxx * syy)


def spearman_ic(signal_values: Sequence[float], forward_returns: Sequence[float]) -> float:
    """Spearman rank correlation between signal values and forward returns.

    Args:
        signal_values: Signal scores for one cross-section (one date, many names).
        forward_returns: Forward returns aligned to ``signal_values``.

    Returns:
        The rank correlation in [-1, 1].

    Raises:
        ValueError: if inputs are misaligned, too short, or have zero variance.
    """
    return _pearson(_average_ranks(signal_values), _average_ranks(forward_returns))


def _betacf(a: float, b: float, x: float, itmax: int = 200, eps: float = 3e-12) -> float:
    """Continued-fraction expansion for the incomplete beta function (Numerical Recipes)."""
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b) for 0 <= x <= 1."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def two_sided_t_pvalue(t_statistic: float, df: float) -> float:
    """Two-sided p-value for a t-statistic under Student's t with ``df`` degrees of freedom.

    Args:
        t_statistic: The observed t-statistic.
        df: Degrees of freedom (> 0).

    Returns:
        The two-sided p-value in [0, 1]. Returns 1.0 for non-positive ``df``.
    """
    if df <= 0:
        return 1.0
    x = df / (df + t_statistic * t_statistic)
    p = _regularized_incomplete_beta(df / 2.0, 0.5, x)
    return min(1.0, max(0.0, p))


# ----------------------------------------------------------------------- forward returns
def compute_forward_returns(
    prices: Sequence[PriceData], horizon_days: int = DEFAULT_FORWARD_HORIZON_DAYS
) -> dict[tuple[str, date], float]:
    """Compute forward total returns from adjusted close over ``horizon_days`` observations.

    The forward return is the label a signal tries to predict, so using future prices here
    is correct (it is the target, not look-ahead leakage in the signal itself).

    Args:
        prices: Price bars (any order); grouped by ticker and sorted internally by date.
        horizon_days: Number of trading observations ahead to measure the return over.

    Returns:
        Mapping of ``(ticker, date)`` to the forward return from that date.

    Raises:
        ValueError: if ``horizon_days`` is not positive.
    """
    if horizon_days <= 0:
        raise ValueError(f"horizon_days must be positive, got {horizon_days}")
    by_ticker: dict[str, list[PriceData]] = defaultdict(list)
    for bar in prices:
        by_ticker[bar.ticker].append(bar)
    out: dict[tuple[str, date], float] = {}
    for ticker, bars in by_ticker.items():
        bars.sort(key=lambda b: b.date)
        for i in range(len(bars) - horizon_days):
            start_px = bars[i].adjusted_close
            end_px = bars[i + horizon_days].adjusted_close
            out[(ticker, bars[i].date)] = end_px / start_px - 1.0
    return out


# --------------------------------------------------------------------------- evaluation
def daily_ics(
    scores: Sequence[SignalScore],
    forward_returns: Mapping[tuple[str, date], float],
    min_cross_section: int = MIN_CROSS_SECTION_SIZE,
) -> list[tuple[date, float]]:
    """Compute one cross-sectional IC per date.

    Args:
        scores: Signal scores across tickers and dates.
        forward_returns: ``(ticker, date)`` -> forward return.
        min_cross_section: Minimum names required to score a date.

    Returns:
        A list of ``(date, ic)`` sorted by date. Dates with too few names, or with zero
        variance in scores or returns, are skipped (and logged at DEBUG).
    """
    by_date: dict[date, list[tuple[float, float]]] = defaultdict(list)
    for score in scores:
        key = (score.ticker, score.date)
        if key in forward_returns:
            by_date[score.date].append((score.raw_score, forward_returns[key]))

    results: list[tuple[date, float]] = []
    for day in sorted(by_date):
        pairs = by_date[day]
        if len(pairs) < min_cross_section:
            _log.debug("ic.skip.small_cross_section", date=str(day), n=len(pairs))
            continue
        signal_values = [p[0] for p in pairs]
        returns = [p[1] for p in pairs]
        try:
            results.append((day, spearman_ic(signal_values, returns)))
        except ValueError as exc:
            _log.debug("ic.skip.degenerate", date=str(day), reason=str(exc))
    return results


def evaluate_signal(
    scores: Sequence[SignalScore],
    forward_returns: Mapping[tuple[str, date], float],
    regimes: Mapping[date, str] | None = None,
    min_cross_section: int = MIN_CROSS_SECTION_SIZE,
) -> ICReport:
    """Evaluate a signal's IC time series into a summary :class:`ICReport`.

    Args:
        scores: Signal scores across tickers and dates.
        forward_returns: ``(ticker, date)`` -> forward return (see :func:`compute_forward_returns`).
        regimes: Optional ``date`` -> regime label, for the per-regime IC breakdown.
        min_cross_section: Minimum names required to score a date.

    Returns:
        An :class:`ICReport`.

    Raises:
        ValueError: if no date had a computable IC.
    """
    series = daily_ics(scores, forward_returns, min_cross_section)
    if not series:
        raise ValueError("no date had a computable IC (check cross-section size and overlap)")

    ics = [ic for _, ic in series]
    n = len(ics)
    mean_ic = statistics.fmean(ics)
    ic_std = statistics.stdev(ics) if n >= 2 else 0.0
    icir = mean_ic / ic_std if ic_std > 0 else 0.0

    if n < 2:
        t_stat, p_value = 0.0, 1.0
    elif ic_std == 0:
        # All ICs identical and non-zero -> infinitely significant in the limit.
        t_stat = math.inf if mean_ic > 0 else -math.inf
        p_value = 0.0
    else:
        t_stat = mean_ic / (ic_std / math.sqrt(n))
        p_value = two_sided_t_pvalue(t_stat, df=n - 1)

    positive_ic_ratio = sum(1 for ic in ics if ic > 0) / n

    by_regime: dict[str, float] = {}
    if regimes is not None:
        grouped: dict[str, list[float]] = defaultdict(list)
        for day, ic in series:
            if day in regimes:
                grouped[regimes[day]].append(ic)
        by_regime = {label: statistics.fmean(values) for label, values in grouped.items()}

    return ICReport(
        mean_ic=mean_ic,
        ic_std=ic_std,
        icir=icir,
        t_statistic=t_stat,
        p_value=p_value,
        positive_ic_ratio=positive_ic_ratio,
        n_periods=n,
        by_regime=by_regime,
    )
