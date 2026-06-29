"""Supply-chain contagion signal (Milestone 3).

Shocks propagate along supply chains with a lag: a supplier's or customer's recent move
carries information about a company's own near-future move. For each subject ticker, the
signal is the weight-weighted average of its related tickers' trailing returns, standardized
cross-sectionally.

Point-in-time safe: only prices on or before the as-of date are used, and only links flagged
point-in-time (PRINCIPLES.md Rule 8).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from src.data.contracts.schemas import PriceData, SignalScore, SupplyChainLink
from src.signals.construction._common import make_scores, zscore

SIGNAL_NAME = "supply_chain_contagion"
SIGNAL_VERSION = "0.1.0"

#: Trailing-return window for related tickers, in trading observations.
DEFAULT_LOOKBACK_DAYS = 21


def _trailing_returns(
    prices: Sequence[PriceData], as_of: date, lookback_days: int
) -> dict[str, float]:
    """Trailing return per ticker over ``lookback_days`` ending on/before ``as_of``."""
    by_ticker: dict[str, list[PriceData]] = defaultdict(list)
    for bar in prices:
        if bar.date <= as_of:
            by_ticker[bar.ticker].append(bar)
    out: dict[str, float] = {}
    for ticker, bars in by_ticker.items():
        bars.sort(key=lambda b: b.date)
        if len(bars) < 2:
            continue
        start_bar = bars[-1 - lookback_days] if len(bars) > lookback_days else bars[0]
        out[ticker] = bars[-1].adjusted_close / start_bar.adjusted_close - 1.0
    return out


def compute_supply_chain_signal(
    links: Sequence[SupplyChainLink],
    prices: Sequence[PriceData],
    as_of: date,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> list[SignalScore]:
    """Compute the supply-chain contagion signal for one as-of date.

    Args:
        links: Directed supplier/customer relationships.
        prices: Price bars for the universe (subjects and their related tickers).
        as_of: The date the signal is computed for (only prices on/before it).
        lookback_days: Trailing-return window for related tickers.

    Returns:
        One :class:`SignalScore` per subject ticker that has at least one related ticker with
        a computable trailing return, sorted by ticker. Empty if none qualify.

    Raises:
        ValueError: if a link is not point-in-time, or ``lookback_days`` <= 0.
    """
    if lookback_days <= 0:
        raise ValueError(f"lookback_days must be positive, got {lookback_days}")

    trailing = _trailing_returns(prices, as_of, lookback_days)

    by_subject: dict[str, list[SupplyChainLink]] = defaultdict(list)
    for link in links:
        if not link.is_point_in_time:
            raise ValueError(
                f"non point-in-time supply-chain link for {link.ticker} cannot be used (Rule 8)"
            )
        by_subject[link.ticker].append(link)

    subjects: list[str] = []
    raw_scores: list[float] = []
    for subject in sorted(by_subject):
        weighted_sum = 0.0
        total_weight = 0.0
        for link in by_subject[subject]:
            related_return = trailing.get(link.related_ticker)
            if related_return is None:
                continue
            weighted_sum += link.weight * related_return
            total_weight += link.weight
        if total_weight == 0:
            continue
        subjects.append(subject)
        raw_scores.append(weighted_sum / total_weight)

    if not subjects:
        return []

    return make_scores(
        subjects,
        zscore(raw_scores),
        signal_name=SIGNAL_NAME,
        signal_version=SIGNAL_VERSION,
        as_of=as_of,
        data_inputs=["supply_chain", "prices"],
    )
