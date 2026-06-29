"""Maximize information ratio across surviving signals (Milestone 5).

The IR-maximizing linear combination of signals has weights proportional to
``Sigma^-1 mu`` where ``mu`` is the vector of mean ICs and ``Sigma`` the covariance of the
signals' IC time series. We add a ridge term for numerical stability and solve the linear
system in pure Python (Gaussian elimination), then normalize to unit L1 so the combination
scale is controlled. ``combine_signals`` applies the weights to produce one combined signal.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date

from src.data.contracts.schemas import SignalScore
from src.signals.construction._common import make_scores, zscore
from src.signals.validation.ic_calculator import MIN_CROSS_SECTION_SIZE, daily_ics

#: Ridge added to the diagonal of the IC covariance for numerical stability.
DEFAULT_RIDGE = 1e-3

COMBINED_SIGNAL_NAME = "combined"
COMBINED_SIGNAL_VERSION = "0.1.0"


def signal_ic_series(
    signals: Mapping[str, Sequence[SignalScore]],
    forward_returns: Mapping[tuple[str, date], float],
    min_cross_section: int = MIN_CROSS_SECTION_SIZE,
) -> dict[str, dict[date, float]]:
    """Per-signal daily IC series (``name`` -> ``date`` -> IC)."""
    return {
        name: dict(daily_ics(scores, forward_returns, min_cross_section))
        for name, scores in signals.items()
    }


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Solve ``matrix @ x = vector`` via Gaussian elimination with partial pivoting.

    Raises:
        ValueError: if the matrix is singular.
    """
    n = len(vector)
    aug = [list(matrix[i]) + [vector[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < 1e-15:
            raise ValueError("singular matrix")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        pivot_value = aug[col][col]
        for r in range(n):
            if r == col:
                continue
            factor = aug[r][col] / pivot_value
            for c in range(col, n + 1):
                aug[r][c] -= factor * aug[col][c]
    return [aug[i][n] / aug[i][i] for i in range(n)]


def optimal_weights(
    ic_series: Mapping[str, Mapping[date, float]], ridge: float = DEFAULT_RIDGE
) -> dict[str, float]:
    """Compute IR-maximizing signal weights (``Sigma^-1 mu``), normalized to unit L1.

    Args:
        ic_series: Per-signal IC time series.
        ridge: Diagonal regularization added to the covariance.

    Returns:
        ``name`` -> weight. Falls back to equal weights when the covariance cannot be
        estimated (fewer than two common dates) or is singular.
    """
    names = sorted(ic_series)
    if not names:
        return {}
    common = sorted(set.intersection(*(set(ic_series[n]) for n in names)))
    if len(common) < 2:
        return {n: 1.0 / len(names) for n in names}

    series = {n: [ic_series[n][d] for d in common] for n in names}
    means = {n: statistics.fmean(series[n]) for n in names}
    mu = [means[n] for n in names]
    k, m = len(names), len(common)
    cov = [[0.0] * k for _ in range(k)]
    for i, ni in enumerate(names):
        for j, nj in enumerate(names):
            cov[i][j] = sum(
                (series[ni][t] - means[ni]) * (series[nj][t] - means[nj]) for t in range(m)
            ) / (m - 1)
        cov[i][i] += ridge

    try:
        raw = _solve(cov, mu)
    except ValueError:
        return {n: 1.0 / len(names) for n in names}

    l1 = sum(abs(w) for w in raw)
    if l1 == 0:
        return {n: 1.0 / k for n in names}
    return {names[i]: raw[i] / l1 for i in range(k)}


def combine_signals(
    signals: Mapping[str, Sequence[SignalScore]],
    weights: Mapping[str, float],
    signal_name: str = COMBINED_SIGNAL_NAME,
    signal_version: str = COMBINED_SIGNAL_VERSION,
) -> list[SignalScore]:
    """Combine signals into one, weighting each signal's per-date z-scored values.

    Args:
        signals: ``name`` -> scores.
        weights: ``name`` -> weight (e.g. from :func:`optimal_weights`).
        signal_name: Name for the combined signal.
        signal_version: Version for the combined signal.

    Returns:
        One combined :class:`SignalScore` per (ticker, date) that appears in any signal.
    """
    by_name_date: dict[str, dict[date, dict[str, float]]] = {
        name: defaultdict(dict) for name in signals
    }
    for name, scores in signals.items():
        for score in scores:
            by_name_date[name][score.date][score.ticker] = score.raw_score

    all_dates = sorted({day for name in signals for day in by_name_date[name]})
    inputs = [signal_name, *sorted(signals)]
    out: list[SignalScore] = []
    for day in all_dates:
        combined: dict[str, float] = defaultdict(float)
        for name in signals:
            day_map = by_name_date[name].get(day)
            if not day_map:
                continue
            tickers = sorted(day_map)
            standardized = zscore([day_map[t] for t in tickers])
            weight = weights.get(name, 0.0)
            for i, ticker in enumerate(tickers):
                combined[ticker] += weight * standardized[i]
        if not combined:
            continue
        tickers = sorted(combined)
        out.extend(
            make_scores(
                tickers,
                [combined[t] for t in tickers],
                signal_name=signal_name,
                signal_version=signal_version,
                as_of=day,
                data_inputs=inputs,
            )
        )
    return out
