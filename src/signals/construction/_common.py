"""Shared cross-sectional helpers for signal construction modules."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from datetime import date

from src.data.contracts.schemas import SignalScore


def zscore(values: Sequence[float]) -> list[float]:
    """Standardize ``values`` cross-sectionally; returns zeros if there is no spread."""
    if len(values) < 2:
        return [0.0] * len(values)
    mean = statistics.fmean(values)
    std = statistics.pstdev(values)
    if std == 0:
        return [0.0] * len(values)
    return [(v - mean) / std for v in values]


def average_ranks(values: Sequence[float]) -> list[float]:
    """Return 1-based ranks of ``values``, averaging ties."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1
    return ranks


def rank01(values: Sequence[float]) -> list[float]:
    """Scale average ranks into [0, 1]; a single value maps to 0.5."""
    n = len(values)
    if n < 2:
        return [0.5] * n
    return [(r - 1.0) / (n - 1.0) for r in average_ranks(values)]


def make_scores(
    tickers: Sequence[str],
    raw_scores: Sequence[float],
    *,
    signal_name: str,
    signal_version: str,
    as_of: date,
    data_inputs: Sequence[str],
) -> list[SignalScore]:
    """Build validated :class:`SignalScore` objects from raw scores (rank computed here).

    Args:
        tickers: Tickers aligned to ``raw_scores``.
        raw_scores: The signal's raw values.
        signal_name: Signal name stamped on every score.
        signal_version: Semver version stamped on every score.
        as_of: The score date.
        data_inputs: Names of the data fields the signal consumed.

    Returns:
        One :class:`SignalScore` per ticker, with cross-sectional ``rank_score`` in [0, 1].
    """
    ranks = rank01(raw_scores)
    return [
        SignalScore(
            ticker=ticker,
            date=as_of,
            signal_name=signal_name,
            signal_version=signal_version,
            raw_score=raw_scores[i],
            rank_score=ranks[i],
            data_inputs=list(data_inputs),
        )
        for i, ticker in enumerate(tickers)
    ]
