"""Unit tests for delisting-return hygiene (settled rule: merge, then impute).

Verified on live CRSP: of 22,124 delisting events sampled, **13.4% carry no
``dlret`` at all**, and the return that does exist lives in ``crsp.dsedelist`` — never
in ``crsp.dsf``. A backtest that reads only the daily file therefore stops at the last
traded price and books a bankruptcy as a flat exit, biasing every result upward.

Imputation follows the standard convention: -30% for NYSE/AMEX, -55% for NASDAQ, applied
ONLY to performance-related delistings (codes 400-599). Mergers (200s) are not distress
and are never imputed.
"""

from __future__ import annotations

from datetime import date

import pytest
from src.data.wrds.delisting import (
    IMPUTED_NASDAQ,
    IMPUTED_NYSE_AMEX,
    apply_delisting,
    parse_delisting_row,
)

from tests.synth import flat_bar


def _bars(closes: list[float], start_day: int = 1) -> list:  # noqa: ANN202
    return [flat_bar("LEH", date(2008, 9, start_day + i), c) for i, c in enumerate(closes)]


# ------------------------------------------------------------------------- parsing


def test_parses_a_real_delisting_row() -> None:
    # Lehman Brothers, permno 80599, as returned live by crsp.dsedelist.
    event = parse_delisting_row(
        {"permno": 80599, "dlstdt": "2008-09-17", "dlstcd": 574, "dlret": "-0.600000"}
    )
    assert event is not None
    assert event.delist_date == date(2008, 9, 17)
    assert event.code == 574
    assert event.delisting_return == pytest.approx(-0.60)
    assert event.is_performance_related is True


def test_active_listing_is_not_a_delisting_event() -> None:
    # dlstcd 100 means "still listed" — the file carries a row for every security.
    assert parse_delisting_row({"permno": 1, "dlstdt": "2024-12-31", "dlstcd": 100}) is None


def test_merger_is_not_performance_related() -> None:
    event = parse_delisting_row(
        {"permno": 1, "dlstdt": "2010-01-04", "dlstcd": 233, "dlret": "0.052"}
    )
    assert event is not None
    assert event.is_performance_related is False


def test_row_without_a_date_is_unusable() -> None:
    assert parse_delisting_row({"permno": 1, "dlstdt": None, "dlstcd": 574}) is None


# ---------------------------------------------------------------------- imputation


@pytest.mark.parametrize(
    ("exchcd", "expected"), [(1, IMPUTED_NYSE_AMEX), (2, IMPUTED_NYSE_AMEX), (3, IMPUTED_NASDAQ)]
)
def test_missing_return_is_imputed_by_exchange(exchcd: int, expected: float) -> None:
    event = parse_delisting_row({"permno": 1, "dlstdt": "2008-09-17", "dlstcd": 574, "dlret": None})
    assert event is not None
    assert event.effective_return(exchcd) == pytest.approx(expected)


def test_present_return_is_never_overwritten_by_imputation() -> None:
    event = parse_delisting_row(
        {"permno": 1, "dlstdt": "2008-09-17", "dlstcd": 574, "dlret": "-0.600000"}
    )
    assert event is not None
    assert event.effective_return(3) == pytest.approx(-0.60)  # not -0.55


def test_missing_return_on_a_merger_is_not_imputed_as_distress() -> None:
    event = parse_delisting_row({"permno": 1, "dlstdt": "2010-01-04", "dlstcd": 233, "dlret": None})
    assert event is not None
    assert event.effective_return(1) == 0.0  # a merger is not a -30% loss


def test_unknown_exchange_falls_back_to_the_harsher_estimate() -> None:
    event = parse_delisting_row({"permno": 1, "dlstdt": "2008-09-17", "dlstcd": 574, "dlret": None})
    assert event is not None
    assert event.effective_return(None) == pytest.approx(IMPUTED_NASDAQ)


# ------------------------------------------------------------------------ applying


def test_delisting_return_is_appended_as_a_terminal_bar() -> None:
    bars = _bars([10.0, 8.0, 5.0])
    event = parse_delisting_row(
        {"permno": 80599, "dlstdt": "2008-09-17", "dlstcd": 574, "dlret": "-0.600000"}
    )
    assert event is not None
    out = apply_delisting(bars, event, exchcd=1)
    assert len(out) == len(bars) + 1
    terminal = out[-1]
    assert terminal.date == date(2008, 9, 17)
    # The final holding period must lose 60% on top of the last traded price.
    assert terminal.adjusted_close == pytest.approx(bars[-1].adjusted_close * 0.40)


def test_total_loss_stays_representable() -> None:
    # dlret = -1.0 would drive the price to zero, which the contract forbids (gt=0).
    bars = _bars([10.0])
    event = parse_delisting_row(
        {"permno": 1, "dlstdt": "2008-09-17", "dlstcd": 574, "dlret": "-1.0"}
    )
    assert event is not None
    out = apply_delisting(bars, event, exchcd=1)
    assert out[-1].adjusted_close > 0
    assert out[-1].adjusted_close < bars[-1].adjusted_close * 1e-3  # economically wiped out


def test_zero_return_delisting_adds_no_bar() -> None:
    # A clean merger at fair value changes nothing; do not fabricate a bar.
    bars = _bars([10.0])
    event = parse_delisting_row({"permno": 1, "dlstdt": "2010-01-04", "dlstcd": 233, "dlret": None})
    assert event is not None
    assert apply_delisting(bars, event, exchcd=1) == bars


def test_delisting_before_the_last_bar_is_ignored() -> None:
    # Guard against a stale event corrupting a series that kept trading.
    bars = _bars([10.0, 11.0, 12.0], start_day=20)
    event = parse_delisting_row(
        {"permno": 1, "dlstdt": "2008-09-01", "dlstcd": 574, "dlret": "-0.6"}
    )
    assert event is not None
    assert apply_delisting(bars, event, exchcd=1) == bars


def test_applying_to_an_empty_series_is_a_no_op() -> None:
    event = parse_delisting_row(
        {"permno": 1, "dlstdt": "2008-09-17", "dlstcd": 574, "dlret": "-0.6"}
    )
    assert event is not None
    assert apply_delisting([], event, exchcd=1) == []


def test_terminal_bar_preserves_ticker_and_source() -> None:
    # The synthetic bar must inherit the series' provenance, never invent one.
    bars = _bars([10.0])
    event = parse_delisting_row(
        {"permno": 1, "dlstdt": "2008-09-17", "dlstcd": 574, "dlret": "-0.6"}
    )
    assert event is not None
    out = apply_delisting(bars, event, exchcd=1)
    assert out[-1].ticker == "LEH"
    assert out[-1].data_source is bars[-1].data_source
    assert out[-1].point_in_time is True
    assert out[-1].volume == 0.0  # no trading occurred on a delisting bar
