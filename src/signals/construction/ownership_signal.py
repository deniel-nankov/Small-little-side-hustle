"""Institutional-ownership momentum signal (Milestone 3).

Rising institutional ownership tends to precede continued buying (smart-money momentum).
The signal is the change in each ticker's institutional ownership fraction over a lookback
window, standardized cross-sectionally. Point-in-time safe: only snapshots dated on or
before the as-of date are used (PRINCIPLES.md Rule 8).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, timedelta

from src.data.contracts.schemas import OwnershipData, SignalScore
from src.signals.construction._common import make_scores, zscore

SIGNAL_NAME = "ownership_momentum"
SIGNAL_VERSION = "0.1.0"

#: Default lookback for the ownership change, in calendar days.
DEFAULT_LOOKBACK_DAYS = 90


def compute_ownership_momentum(
    ownership: Sequence[OwnershipData],
    as_of: date,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[SignalScore]:
    """Compute the institutional-ownership momentum signal for one as-of date.

    Args:
        ownership: Ownership snapshots (any tickers/dates); filtered internally.
        as_of: The date the signal is computed for (only snapshots on/before it).
        lookback_days: Window over which the ownership change is measured.

    Returns:
        One :class:`SignalScore` per ticker with at least one usable snapshot, sorted by
        ticker. A ticker with a single snapshot contributes zero momentum. Empty if no
        ticker qualifies.

    Raises:
        ValueError: if a matching record is not point-in-time, or ``lookback_days`` <= 0.
    """
    if lookback_days <= 0:
        raise ValueError(f"lookback_days must be positive, got {lookback_days}")

    by_ticker: dict[str, list[OwnershipData]] = defaultdict(list)
    for record in ownership:
        if record.as_of_date > as_of:
            continue
        if not record.is_point_in_time:
            raise ValueError(
                f"non point-in-time ownership for {record.ticker} cannot be used (Rule 8)"
            )
        by_ticker[record.ticker].append(record)

    tickers = sorted(by_ticker)
    if not tickers:
        return []

    momentum: list[float] = []
    for ticker in tickers:
        snapshots = sorted(by_ticker[ticker], key=lambda r: r.as_of_date)
        latest = snapshots[-1]
        cutoff = latest.as_of_date - timedelta(days=lookback_days)
        earlier = [s for s in snapshots if s.as_of_date <= cutoff]
        baseline = earlier[-1] if earlier else snapshots[0]
        momentum.append(latest.institutional_ownership_pct - baseline.institutional_ownership_pct)

    return make_scores(
        tickers,
        zscore(momentum),
        signal_name=SIGNAL_NAME,
        signal_version=SIGNAL_VERSION,
        as_of=as_of,
        data_inputs=["ownership"],
    )
