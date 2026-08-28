"""CPI deflation so the universe holds a constant REAL size across the sample.

A fixed nominal band selects different kinds of companies in different decades: $300M was
a mid-sized company in 1995 and is a micro cap in 2024. Measured on live CRSP, NYSE size
deciles 6-8 drifted from $357M-$1.6B (1995) to $1.9B-$12.5B (2024) — so neither a fixed
nominal band nor a fixed percentile keeps "small cap" economically constant.

Deflating the bounds to constant base-year dollars does. It also matches the economics of
the structural thesis: analyst-coverage and institutional-eligibility thresholds track
real company size more closely than they track market percentile.

Series: **CPI-U, annual averages, 1982-84 = 100** (BLS series ``CUUR0000SA0``). Embedded
rather than fetched so backtests stay deterministic and offline; CPI is freely available
from BLS/FRED and is live-able, so nothing here blocks live deployment. Verify against
BLS before extending the series.
"""

from __future__ import annotations

#: The year all bounds are expressed in.
BASE_YEAR = 2024

#: CPI-U annual averages (1982-84 = 100), BLS series CUUR0000SA0.
CPI_U_ANNUAL: dict[int, float] = {
    1990: 130.7, 1991: 136.2, 1992: 140.3, 1993: 144.5, 1994: 148.2,
    1995: 152.4, 1996: 156.9, 1997: 160.5, 1998: 163.0, 1999: 166.6,
    2000: 172.2, 2001: 177.1, 2002: 179.9, 2003: 184.0, 2004: 188.9,
    2005: 195.3, 2006: 201.6, 2007: 207.3, 2008: 215.3, 2009: 214.5,
    2010: 218.1, 2011: 224.9, 2012: 229.6, 2013: 233.0, 2014: 236.7,
    2015: 237.0, 2016: 240.0, 2017: 245.1, 2018: 251.1, 2019: 255.7,
    2020: 258.8, 2021: 271.0, 2022: 292.7, 2023: 304.7, 2024: 313.7,
}  # fmt: skip


def to_base_year_dollars(nominal: float, year: int) -> float:
    """Convert ``nominal`` dollars observed in ``year`` into base-year dollars.

    Args:
        nominal: An amount in that year's dollars.
        year: The year the amount was observed.

    Returns:
        The equivalent amount in :data:`BASE_YEAR` dollars.

    Raises:
        ValueError: if the year is outside the embedded CPI series — guessing an index
            level would silently mis-size the universe.
    """
    if year not in CPI_U_ANNUAL:
        span = f"{min(CPI_U_ANNUAL)}-{max(CPI_U_ANNUAL)}"
        raise ValueError(f"no CPI value for {year}; series covers {span}")
    return nominal * CPI_U_ANNUAL[BASE_YEAR] / CPI_U_ANNUAL[year]


def deflate_bounds(low: float, high: float, year: int) -> tuple[float, float]:
    """Express base-year dollar bounds in ``year``'s nominal dollars.

    Args:
        low: Lower bound in :data:`BASE_YEAR` dollars.
        high: Upper bound in :data:`BASE_YEAR` dollars.
        year: The formation year to express the bounds in.

    Returns:
        ``(low, high)`` in that year's nominal dollars, so they can be compared directly
        against market caps computed from that year's prices.

    Raises:
        ValueError: if the year is outside the embedded CPI series.
    """
    if year not in CPI_U_ANNUAL:
        span = f"{min(CPI_U_ANNUAL)}-{max(CPI_U_ANNUAL)}"
        raise ValueError(f"no CPI value for {year}; series covers {span}")
    factor = CPI_U_ANNUAL[year] / CPI_U_ANNUAL[BASE_YEAR]
    return low * factor, high * factor
