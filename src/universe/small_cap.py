"""Point-in-time small-cap universe construction from the CRSP monthly cross-section.

CRSP itself is survivorship-bias-free; **universe construction is where the bias actually
enters**. Selecting from today's constituent list quietly drops every company that has
since died. So the universe is rebuilt from the cross-section as it stood on each
formation date, using only information available then.

Four conventions matter, each a way to get the wrong companies without noticing:

* **``shrout`` is in THOUSANDS.** Omitting the factor understates every market cap by
  1000x and selects an entirely different set of names.
* **``prc`` is negative for a bid/ask midpoint**; the magnitude is still the price.
* **Size breakpoints come from NYSE listings only** — the academic standard. NASDAQ's long
  tail of micro listings would otherwise drag every breakpoint down, so "decile 6" would
  mean something far smaller than intended.
* **``shrcd`` 10/11 keeps US common stock**, excluding ADRs, REITs and closed-end funds.

Deciles are used rather than fixed dollar bounds because a fixed $300M floor means
something very different in 1990 than in 2024; deciles are scale-invariant across the
sample. The realized dollar range is reported so it can be checked against intent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.monitoring.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_log = get_logger(__name__)

MSF_TABLE = "crsp.msf"

#: CRSP reports shares outstanding in thousands.
SHROUT_MULTIPLIER = 1000.0

#: CRSP share codes for ordinary US common stock.
COMMON_SHARE_CODES = frozenset({10, 11})

#: CRSP header exchange code for NYSE, the breakpoint reference universe.
NYSE_EXCHANGE_CODE = 1

_DECILES = 10


@dataclass(frozen=True)
class UniverseSpec:
    """Universe definition, fixed up front so nothing is tuned after seeing results."""

    min_decile: int = 6
    max_decile: int = 8
    min_price: float = 5.0


@dataclass(frozen=True)
class UniverseMember:
    """One security selected into the universe on a formation date."""

    permno: int
    market_cap: float
    decile: int


def _to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def market_cap_from_row(row: Mapping[str, Any]) -> float | None:
    """Return market capitalisation in dollars, or None when the row is unusable.

    Args:
        row: A ``crsp.msf`` row carrying ``prc`` and ``shrout``.

    Returns:
        ``|prc| * shrout * 1000``, or None if either field is missing or shares are zero.
    """
    price, shares = _to_float(row.get("prc")), _to_float(row.get("shrout"))
    if price is None or shares is None or shares <= 0 or price == 0:
        return None
    return abs(price) * shares * SHROUT_MULTIPLIER


def nyse_breakpoints(rows: Sequence[Mapping[str, Any]]) -> list[float]:
    """Return the nine NYSE market-cap decile breakpoints for one cross-section.

    Args:
        rows: The full cross-section (all exchanges); NYSE names are selected internally.

    Returns:
        Nine ascending cut points, or an empty list when there are too few NYSE names.
    """
    caps = sorted(
        cap
        for row in rows
        if _to_float(row.get("hexcd")) == NYSE_EXCHANGE_CODE
        and (cap := market_cap_from_row(row)) is not None
    )
    if len(caps) < _DECILES:
        return []
    return [caps[round(len(caps) * i / _DECILES)] for i in range(1, _DECILES)]


def assign_decile(market_cap: float, breakpoints: Sequence[float]) -> int:
    """Assign a size decile (1 = smallest, 10 = largest) from NYSE breakpoints."""
    decile = 1
    for cut in breakpoints:
        if market_cap < cut:
            break
        decile += 1
    return min(decile, _DECILES)


def select_universe(
    cross_section: Sequence[Mapping[str, Any]],
    share_codes: Mapping[int, int],
    spec: UniverseSpec,
) -> list[UniverseMember]:
    """Select the universe from one date's cross-section.

    Args:
        cross_section: All ``crsp.msf`` rows for the formation date.
        share_codes: ``permno -> shrcd`` valid on that date. A permno absent from the map
            is EXCLUDED — an unknown share class is not an invitation to guess.
        spec: The universe definition (fixed in advance).

    Returns:
        Members sorted by market cap ascending.
    """
    breakpoints = nyse_breakpoints(cross_section)
    members: list[UniverseMember] = []
    for row in cross_section:
        permno_raw = _to_float(row.get("permno"))
        cap = market_cap_from_row(row)
        price = _to_float(row.get("prc"))
        if permno_raw is None or cap is None or price is None:
            continue
        permno = int(permno_raw)
        if share_codes.get(permno) not in COMMON_SHARE_CODES:
            continue
        if abs(price) < spec.min_price:
            continue
        decile = assign_decile(cap, breakpoints)
        if spec.min_decile <= decile <= spec.max_decile:
            members.append(UniverseMember(permno=permno, market_cap=cap, decile=decile))
    members.sort(key=lambda m: m.market_cap)
    _log.info(
        "universe.selected",
        candidates=len(cross_section),
        selected=len(members),
        deciles=f"{spec.min_decile}-{spec.max_decile}",
        min_cap=round(members[0].market_cap / 1e6, 1) if members else None,
        max_cap=round(members[-1].market_cap / 1e6, 1) if members else None,
    )
    return members
