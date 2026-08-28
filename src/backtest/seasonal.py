"""Annual formation/holding long-short harness.

One observation per year: rank the universe on a formation-date signal, go long the
bottom quintile and short the top, hold for a fixed window, and measure the spread net of
the stated cost assumption.

Deliberate choices that keep the result honest:

* **Quintiles, not deciles** — with a few hundred small caps a decile is thin enough that
  a handful of names drives the result.
* **A leg needs at least two names.** With fewer, a "quintile" is one stock and the
  spread is an anecdote; the year is refused instead.
* **Names without a holding-period return are excluded, never zero-filled.** Treating a
  missing return as flat would quietly convert delistings into break-even exits — the
  same upward bias the delisting merge exists to remove. (Merged delisting returns mean
  a bankrupt name *has* a return, so exclusion here is genuinely for missing data.)
* **Cost is charged once per round trip** on the combined position.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.monitoring.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_log = get_logger(__name__)

#: Stated cost assumption: 30 bps round trip, charged on every reported result.
ROUND_TRIP_COST = 0.0030

#: Fraction of the cross-section in each leg.
QUINTILE = 0.2

#: Minimum names per leg before a year is scoreable.
MIN_LEG = 2


@dataclass(frozen=True)
class AnnualResult:
    """One year's long-short spread."""

    year: int
    long_return: float
    short_return: float
    net_return: float
    n_long: int
    n_short: int


def quintile_split(signals: Mapping[int, float]) -> tuple[list[int], list[int]]:
    """Split the cross-section into bottom (long) and top (short) quintiles.

    Args:
        signals: ``permno -> signal value`` at the formation date. Lower is "more loser".

    Returns:
        ``(longs, shorts)``; both empty when the cross-section is too thin for a leg of
        at least :data:`MIN_LEG` names.
    """
    ordered = sorted(signals, key=lambda p: (signals[p], p))
    size = int(len(ordered) * QUINTILE)
    if size < MIN_LEG:
        return [], []
    return ordered[:size], ordered[-size:]


def spread_return(
    longs: Sequence[int],
    shorts: Sequence[int],
    holding_returns: Mapping[int, float],
    *,
    cost: float = ROUND_TRIP_COST,
) -> float | None:
    """Return the net long-short spread, or None when either leg has no data.

    Args:
        longs: Permnos in the long leg.
        shorts: Permnos in the short leg.
        holding_returns: ``permno -> holding-period return``. Names absent from this map
            are excluded from their leg rather than treated as flat.
        cost: Round-trip cost charged once on the combined position.

    Returns:
        ``mean(long) - mean(short) - cost``, or None if either leg ends up empty.
    """
    long_rets = [holding_returns[p] for p in longs if p in holding_returns]
    short_rets = [holding_returns[p] for p in shorts if p in holding_returns]
    if not long_rets or not short_rets:
        return None
    return sum(long_rets) / len(long_rets) - sum(short_rets) / len(short_rets) - cost


def run_annual_spread(
    *,
    year: int,
    signals: Mapping[int, float],
    holding_returns: Mapping[int, float],
    cost: float = ROUND_TRIP_COST,
) -> AnnualResult | None:
    """Score one formation year.

    Args:
        year: Formation year (for reporting).
        signals: ``permno -> formation-date signal``.
        holding_returns: ``permno -> holding-period return``.
        cost: Round-trip cost assumption.

    Returns:
        The year's :class:`AnnualResult`, or None when the universe is too thin or a leg
        has no return data.
    """
    longs, shorts = quintile_split(signals)
    if not longs or not shorts:
        _log.info("seasonal.year_skipped", year=year, universe=len(signals), reason="thin")
        return None
    long_rets = [holding_returns[p] for p in longs if p in holding_returns]
    short_rets = [holding_returns[p] for p in shorts if p in holding_returns]
    if not long_rets or not short_rets:
        _log.info("seasonal.year_skipped", year=year, reason="no holding returns")
        return None
    long_avg = sum(long_rets) / len(long_rets)
    short_avg = sum(short_rets) / len(short_rets)
    return AnnualResult(
        year=year,
        long_return=long_avg,
        short_return=short_avg,
        net_return=long_avg - short_avg - cost,
        n_long=len(long_rets),
        n_short=len(short_rets),
    )
