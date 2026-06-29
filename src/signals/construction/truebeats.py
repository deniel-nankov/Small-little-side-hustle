"""DIY earnings-surprise prediction signal (Milestone 3).

Re-implements the Vinesh Jha / FactSet TrueBeats methodology from FactSet's blog. The
signal predicts the direction and magnitude of the next earnings surprise from three
components, combined cross-sectionally:

* **Expert beat** — an accuracy-weighted consensus minus the naive equal-weight consensus.
  Weighting analysts by historical accuracy produces a "smarter consensus"; the gap between
  it and the simple consensus is the predicted surprise direction.
* **Trend beat** — surprises cluster within peer groups defined by *shared analyst
  coverage* (not GICS sector). A name's trend component is the average expert-beat of the
  peers it shares analysts with (contagion).
* **Management beat** — high disagreement among analysts (estimate dispersion) signals miss
  risk, so larger dispersion lowers the score.

The three components are each standardized cross-sectionally and combined with weights
(equal by default). Output is one :class:`SignalScore` per ticker for the as-of date.

Pure standard library; no native dependencies. Point-in-time safe: only estimates dated on
or before the as-of date are used (PRINCIPLES.md Rule 8).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from src.data.contracts.schemas import EstimateData, Metric, SignalScore

SIGNAL_NAME = "truebeats"
SIGNAL_VERSION = "0.1.0"  # pre-validation; bumps on promotion through the registry

#: Used when an analyst's historical accuracy is unknown.
DEFAULT_ANALYST_ACCURACY = 0.5


@dataclass(frozen=True)
class TrueBeatsWeights:
    """Component weights for the combined TrueBeats score (need not sum to 1)."""

    expert: float
    trend: float
    management: float


DEFAULT_WEIGHTS = TrueBeatsWeights(expert=1 / 3, trend=1 / 3, management=1 / 3)


def _zscore(values: Sequence[float]) -> list[float]:
    """Standardize ``values`` cross-sectionally; returns zeros if there is no spread."""
    if len(values) < 2:
        return [0.0] * len(values)
    mean = statistics.fmean(values)
    std = statistics.pstdev(values)
    if std == 0:
        return [0.0] * len(values)
    return [(v - mean) / std for v in values]


def _average_ranks(values: Sequence[float]) -> list[float]:
    """Return 1-based ranks, averaging ties (kept local to avoid a validation import)."""
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


def _rank01(values: Sequence[float]) -> list[float]:
    """Scale average ranks into [0, 1]; a single value maps to 0.5."""
    n = len(values)
    if n < 2:
        return [0.5] * n
    return [(r - 1.0) / (n - 1.0) for r in _average_ranks(values)]


def compute_truebeats(
    estimates: Sequence[EstimateData],
    as_of: date,
    metric: Metric = Metric.eps,
    weights: TrueBeatsWeights = DEFAULT_WEIGHTS,
) -> list[SignalScore]:
    """Compute the TrueBeats signal for one as-of date.

    Args:
        estimates: Analyst estimates (any tickers/dates); filtered internally.
        as_of: The date the signal is computed for. Only estimates on or before this date
            are used (point-in-time).
        metric: Which estimate metric to build the signal from (default EPS).
        weights: Component weights.

    Returns:
        One :class:`SignalScore` per ticker that has at least one usable estimate, sorted by
        ticker. Returns an empty list if no ticker qualifies.

    Raises:
        ValueError: if a matching estimate is not point-in-time (look-ahead unsafe).
    """
    relevant: list[EstimateData] = []
    for estimate in estimates:
        if estimate.metric != metric or estimate.estimate_date > as_of:
            continue
        if not estimate.is_point_in_time:
            raise ValueError(
                f"non point-in-time estimate for {estimate.ticker} cannot be used (Rule 8)"
            )
        relevant.append(estimate)

    by_ticker: dict[str, list[EstimateData]] = defaultdict(list)
    for estimate in relevant:
        by_ticker[estimate.ticker].append(estimate)
    tickers = sorted(by_ticker)
    if not tickers:
        return []

    expert_beat: dict[str, float] = {}
    dispersion: dict[str, float] = {}
    analyst_sets: dict[str, set[str]] = {}
    for ticker in tickers:
        rows = by_ticker[ticker]
        values = [r.value for r in rows]
        accuracies = [
            r.analyst_accuracy if r.analyst_accuracy is not None else DEFAULT_ANALYST_ACCURACY
            for r in rows
        ]
        simple_consensus = statistics.fmean(values)
        total_weight = sum(accuracies)
        if total_weight > 0:
            expert_consensus = (
                sum(a * v for a, v in zip(accuracies, values, strict=True)) / total_weight
            )
        else:
            expert_consensus = simple_consensus
        expert_beat[ticker] = expert_consensus - simple_consensus
        dispersion[ticker] = statistics.pstdev(values) if len(values) > 1 else 0.0
        analyst_sets[ticker] = {r.analyst_id for r in rows}

    trend: dict[str, float] = {}
    for ticker in tickers:
        peers = [
            other
            for other in tickers
            if other != ticker and analyst_sets[ticker] & analyst_sets[other]
        ]
        trend[ticker] = statistics.fmean(expert_beat[p] for p in peers) if peers else 0.0

    expert_z = _zscore([expert_beat[t] for t in tickers])
    trend_z = _zscore([trend[t] for t in tickers])
    management_z = _zscore([-dispersion[t] for t in tickers])  # more disagreement -> lower
    raw_scores = [
        weights.expert * expert_z[i]
        + weights.trend * trend_z[i]
        + weights.management * management_z[i]
        for i in range(len(tickers))
    ]
    rank_scores = _rank01(raw_scores)

    return [
        SignalScore(
            ticker=ticker,
            date=as_of,
            signal_name=SIGNAL_NAME,
            signal_version=SIGNAL_VERSION,
            raw_score=raw_scores[i],
            rank_score=rank_scores[i],
            data_inputs=["estimates", metric.value],
        )
        for i, ticker in enumerate(tickers)
    ]
