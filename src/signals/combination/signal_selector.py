"""Remove redundant or correlated signals before weighting (Milestone 5).

Greedily keep signals in priority order, dropping any whose average cross-sectional rank
correlation with an already-kept signal meets or exceeds a threshold. This keeps the most
information per unit of redundancy before the optimal-weights step.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from src.data.contracts.schemas import SignalScore
from src.signals.validation.ic_calculator import MIN_CROSS_SECTION_SIZE, spearman_ic

#: Default redundancy threshold (|rho| >= this -> drop).
DEFAULT_MAX_CORRELATION = 0.5


@dataclass(frozen=True)
class SelectionResult:
    """Which signals survived de-duplication and why the others were dropped."""

    kept: list[str]
    dropped: dict[str, str] = field(default_factory=dict)  # name -> reason


def _by_date(scores: Sequence[SignalScore]) -> dict[date, dict[str, float]]:
    out: dict[date, dict[str, float]] = defaultdict(dict)
    for score in scores:
        out[score.date][score.ticker] = score.raw_score
    return out


def average_correlation(
    a_scores: Sequence[SignalScore],
    b_scores: Sequence[SignalScore],
    min_cross_section: int = MIN_CROSS_SECTION_SIZE,
) -> float | None:
    """Mean signed cross-sectional Spearman correlation between two signals, or None.

    Args:
        a_scores: First signal's scores.
        b_scores: Second signal's scores.
        min_cross_section: Minimum overlapping names required to score a date.

    Returns:
        The average per-date rank correlation, or None if no date overlapped enough.
    """
    a_by, b_by = _by_date(a_scores), _by_date(b_scores)
    per_date: list[float] = []
    for day, a_map in a_by.items():
        b_map = b_by.get(day)
        if not b_map:
            continue
        common = sorted(set(a_map) & set(b_map))
        if len(common) < min_cross_section:
            continue
        try:
            per_date.append(spearman_ic([a_map[t] for t in common], [b_map[t] for t in common]))
        except ValueError:
            continue
    return statistics.fmean(per_date) if per_date else None


def select_signals(
    signals: Mapping[str, Sequence[SignalScore]],
    max_correlation: float = DEFAULT_MAX_CORRELATION,
    priority: Sequence[str] | None = None,
    min_cross_section: int = MIN_CROSS_SECTION_SIZE,
) -> SelectionResult:
    """Greedily de-duplicate correlated signals.

    Args:
        signals: ``name`` -> scores.
        max_correlation: Drop a signal whose ``|rho|`` with a kept signal is >= this.
        priority: Order to consider signals (higher quality first). Defaults to mapping order.
        min_cross_section: Minimum overlapping names required to score a date.

    Returns:
        A :class:`SelectionResult` listing kept signals and reasons for dropped ones.
    """
    ordered = list(priority) if priority else list(signals)
    ordered += [name for name in signals if name not in ordered]

    kept: list[str] = []
    dropped: dict[str, str] = {}
    for name in ordered:
        if name not in signals:
            continue
        conflict: tuple[str, float] | None = None
        for kept_name in kept:
            rho = average_correlation(signals[name], signals[kept_name], min_cross_section)
            if rho is not None and abs(rho) >= max_correlation:
                conflict = (kept_name, rho)
                break
        if conflict is None:
            kept.append(name)
        else:
            dropped[name] = f"correlated with {conflict[0]} (rho={conflict[1]:.2f})"
    return SelectionResult(kept=kept, dropped=dropped)
