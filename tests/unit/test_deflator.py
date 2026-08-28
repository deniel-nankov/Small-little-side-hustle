"""Unit tests for the CPI deflator that keeps the universe a constant REAL size.

A fixed nominal band means different things across decades: $300M in 1995 was a
mid-sized company, $300M in 2024 is a micro cap. Deflating to constant 2024 dollars keeps
"small cap" economically identical in every year of the sample, which is the only way a
1990-2024 backtest selects comparable companies throughout.
"""

from __future__ import annotations

import pytest
from src.universe.deflator import (
    BASE_YEAR,
    CPI_U_ANNUAL,
    deflate_bounds,
    to_base_year_dollars,
)


def test_series_spans_the_backtest_sample() -> None:
    assert min(CPI_U_ANNUAL) <= 1990
    assert max(CPI_U_ANNUAL) >= 2024
    assert BASE_YEAR == 2024


def test_only_2009_shows_deflation() -> None:
    # A real fact worth pinning: US CPI-U fell exactly once in this sample, in 2009
    # (215.3 -> 214.5) during the financial crisis. Any other decline is a typo.
    years = sorted(CPI_U_ANNUAL)
    declines = [
        y for prev, y in zip(years, years[1:], strict=False) if CPI_U_ANNUAL[y] < CPI_U_ANNUAL[prev]
    ]
    assert declines == [2009]


def test_base_year_dollars_are_unchanged() -> None:
    assert to_base_year_dollars(1_000.0, BASE_YEAR) == pytest.approx(1_000.0)


def test_older_dollars_are_worth_more_in_base_year_terms() -> None:
    # $1 in 1995 buys more than $1 in 2024, so it converts UP.
    assert to_base_year_dollars(1.0, 1995) > 1.0


def test_prices_roughly_doubled_from_1995_to_2024() -> None:
    # Sanity anchor against the published series: CPI-U 2024 / 1995 is about 2.
    ratio = CPI_U_ANNUAL[BASE_YEAR] / CPI_U_ANNUAL[1995]
    assert 1.9 < ratio < 2.2


def test_unknown_year_raises_rather_than_guessing() -> None:
    with pytest.raises(ValueError, match="no CPI"):
        to_base_year_dollars(100.0, 1850)


# ------------------------------------------------------------------- bound deflation


def test_bounds_shrink_in_nominal_terms_for_earlier_years() -> None:
    # A $300M-$2B band in 2024 dollars was a smaller NOMINAL band in 1995.
    low_1995, high_1995 = deflate_bounds(300e6, 2e9, 1995)
    assert low_1995 < 300e6
    assert high_1995 < 2e9
    assert low_1995 < high_1995


def test_bounds_are_identity_in_the_base_year() -> None:
    low, high = deflate_bounds(300e6, 2e9, BASE_YEAR)
    assert (low, high) == pytest.approx((300e6, 2e9))


def test_deflated_band_keeps_its_ratio() -> None:
    # Deflation must scale both ends equally; the band's shape is preserved.
    low, high = deflate_bounds(300e6, 2e9, 1995)
    assert high / low == pytest.approx(2e9 / 300e6)
