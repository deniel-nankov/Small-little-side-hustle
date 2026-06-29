"""Fundamental factor signal (Milestone 3).

Combines three point-in-time fundamental factors into one cross-sectional score:

* **Accruals** — ``(net_income - operating_cash_flow) / total_assets``. Low (or negative)
  accruals indicate higher earnings quality, so the signal uses *minus* accruals.
* **ROA** — ``net_income / total_assets``. Higher is better.
* **Revenue acceleration** — the change in revenue growth (``g_t - g_{t-1}``); requires
  three fiscal periods, otherwise contributes zero for that ticker.

Each factor is standardized cross-sectionally and combined with weights (equal by default).
A full Piotroski F-score (nine binary tests) is a future extension that needs more balance
sheet fields; this module ships the highest-signal subset. Point-in-time safe: only periods
reported on or before the as-of date are used (PRINCIPLES.md Rule 8).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from src.data.contracts.schemas import FundamentalData, SignalScore
from src.signals.construction._common import make_scores, zscore

SIGNAL_NAME = "fundamental_factors"
SIGNAL_VERSION = "0.1.0"


@dataclass(frozen=True)
class FundamentalWeights:
    """Component weights for the combined fundamental score (need not sum to 1)."""

    accruals: float
    roa: float
    revenue_acceleration: float


DEFAULT_WEIGHTS = FundamentalWeights(accruals=1 / 3, roa=1 / 3, revenue_acceleration=1 / 3)


def _revenue_acceleration(revenues: Sequence[float]) -> float:
    """Change in revenue growth between the two most recent periods (0 if < 3 periods)."""
    if len(revenues) < 3 or revenues[-2] == 0 or revenues[-3] == 0:
        return 0.0
    growth_recent = revenues[-1] / revenues[-2] - 1.0
    growth_prior = revenues[-2] / revenues[-3] - 1.0
    return growth_recent - growth_prior


def compute_fundamental_factors(
    fundamentals: Sequence[FundamentalData],
    as_of: date,
    weights: FundamentalWeights = DEFAULT_WEIGHTS,
) -> list[SignalScore]:
    """Compute the fundamental-factor signal for one as-of date.

    Args:
        fundamentals: Point-in-time fundamentals (any tickers/periods); filtered internally.
        as_of: The date the signal is computed for (only periods reported on/before it).
        weights: Component weights.

    Returns:
        One :class:`SignalScore` per ticker with at least one usable period, sorted by ticker.
        Empty if no ticker qualifies.

    Raises:
        ValueError: if a matching record is not point-in-time (look-ahead unsafe).
    """
    by_ticker: dict[str, list[FundamentalData]] = defaultdict(list)
    for record in fundamentals:
        if record.report_date > as_of:
            continue
        if not record.is_point_in_time:
            raise ValueError(
                f"non point-in-time fundamentals for {record.ticker} cannot be used (Rule 8)"
            )
        by_ticker[record.ticker].append(record)

    tickers = sorted(by_ticker)
    if not tickers:
        return []

    accruals: list[float] = []
    roa: list[float] = []
    acceleration: list[float] = []
    for ticker in tickers:
        periods = sorted(by_ticker[ticker], key=lambda r: r.report_date)
        latest = periods[-1]
        accruals.append((latest.net_income - latest.operating_cash_flow) / latest.total_assets)
        roa.append(latest.net_income / latest.total_assets)
        acceleration.append(_revenue_acceleration([p.revenue for p in periods]))

    accruals_z = zscore([-a for a in accruals])  # low accruals -> high score
    roa_z = zscore(roa)
    acceleration_z = zscore(acceleration)
    raw_scores = [
        weights.accruals * accruals_z[i]
        + weights.roa * roa_z[i]
        + weights.revenue_acceleration * acceleration_z[i]
        for i in range(len(tickers))
    ]
    return make_scores(
        tickers,
        raw_scores,
        signal_name=SIGNAL_NAME,
        signal_version=SIGNAL_VERSION,
        as_of=as_of,
        data_inputs=["fundamentals"],
    )
