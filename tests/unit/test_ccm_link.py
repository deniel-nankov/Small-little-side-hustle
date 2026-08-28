"""Unit tests for CRSP/Compustat link hygiene (settled rule: LC/LU + P/C + date ranges).

Measured live on ``crsp.ccmxpf_lnkhist``: 123,388 rows, of which only LC (17,932) and
LU (15,945) are research-grade — **73% of the table is unusable**. Two distinct
look-ahead paths exist if the link is used naively:

* ignoring ``linkdt``/``linkenddt`` attaches a company's financials to a security in
  periods when the link was not valid (e.g. post-merger figures on a pre-merger stub);
* ignoring ``linkprim`` returns duplicate rows, silently double-weighting a name.

26,386 links are open-ended (null ``linkenddt``) and must be treated as still valid.
"""

from __future__ import annotations

from datetime import date

import pytest
from src.data.wrds.ccm_link import (
    USABLE_LINKPRIM,
    USABLE_LINKTYPES,
    CCMLinkIndex,
    parse_link_row,
)


def _row(**kw: object) -> dict:
    base = {
        "gvkey": "001690",
        "lpermno": 14593,
        "lpermco": 7,
        "linktype": "LC",
        "linkprim": "P",
        "linkdt": "1980-12-12",
        "linkenddt": "2024-12-31",
        "liid": "01",
    }
    return {**base, **kw}


# ------------------------------------------------------------------------- parsing


def test_parses_a_research_grade_link() -> None:
    link = parse_link_row(_row())
    assert link is not None
    assert link.gvkey == "001690"
    assert link.permno == 14593
    assert link.start == date(1980, 12, 12)
    assert link.end == date(2024, 12, 31)


@pytest.mark.parametrize("linktype", ["NR", "NU", "LX", "LD", "LN", "LS", "NP"])
def test_non_research_link_types_are_rejected(linktype: str) -> None:
    # NR + NU alone are 80,867 of 123,388 rows — unresearched, not usable.
    assert parse_link_row(_row(linktype=linktype)) is None


@pytest.mark.parametrize("linkprim", ["N", "J"])
def test_non_primary_links_are_rejected(linkprim: str) -> None:
    # Secondary/joiner rows duplicate a name and would double-weight it.
    assert parse_link_row(_row(linkprim=linkprim)) is None


def test_only_lc_and_lu_are_accepted() -> None:
    assert frozenset({"LC", "LU"}) == USABLE_LINKTYPES
    assert frozenset({"P", "C"}) == USABLE_LINKPRIM
    for good in ("LC", "LU"):
        assert parse_link_row(_row(linktype=good)) is not None


def test_link_without_a_permno_is_unusable() -> None:
    # Live: unusable link types frequently carry a null lpermno.
    assert parse_link_row(_row(lpermno=None)) is None


def test_open_ended_link_is_still_valid() -> None:
    link = parse_link_row(_row(linkenddt=None))
    assert link is not None
    assert link.end is None
    assert link.covers(date(2024, 6, 30)) is True


def test_link_without_a_start_date_is_unusable() -> None:
    assert parse_link_row(_row(linkdt=None)) is None


# ------------------------------------------------------------------ date coverage


def test_coverage_respects_the_link_window_inclusively() -> None:
    link = parse_link_row(_row(linkdt="2000-01-01", linkenddt="2010-12-31"))
    assert link is not None
    assert link.covers(date(1999, 12, 31)) is False
    assert link.covers(date(2000, 1, 1)) is True  # boundary is inclusive
    assert link.covers(date(2010, 12, 31)) is True
    assert link.covers(date(2011, 1, 1)) is False


# -------------------------------------------------------------------------- index


def _index() -> CCMLinkIndex:
    return CCMLinkIndex.from_rows(
        [
            _row(gvkey="001690", lpermno=14593, linkdt="1980-12-12", linkenddt=None),
            # Same gvkey linked to a DIFFERENT permno in an earlier era.
            _row(gvkey="002000", lpermno=11111, linkdt="1970-01-01", linkenddt="1989-12-31"),
            _row(gvkey="002000", lpermno=22222, linkdt="1990-01-01", linkenddt="2005-12-31"),
            _row(linktype="NR", gvkey="009999", lpermno=99999),  # must be filtered out
        ]
    )


def test_index_resolves_gvkey_to_the_permno_valid_on_that_date() -> None:
    idx = _index()
    assert idx.permno_for_gvkey("002000", date(1985, 6, 1)) == 11111
    assert idx.permno_for_gvkey("002000", date(1995, 6, 1)) == 22222
    assert idx.permno_for_gvkey("002000", date(2020, 6, 1)) is None  # link had ended


def test_index_resolves_permno_to_gvkey() -> None:
    idx = _index()
    assert idx.gvkey_for_permno(14593, date(2020, 1, 2)) == "001690"
    assert idx.gvkey_for_permno(22222, date(1995, 6, 1)) == "002000"


def test_index_excludes_unusable_rows_entirely() -> None:
    idx = _index()
    assert idx.permno_for_gvkey("009999", date(2020, 1, 2)) is None
    assert idx.rejected == 1
    assert idx.usable == 3


def test_index_reports_the_filtered_fraction() -> None:
    idx = _index()
    assert idx.usable_fraction == pytest.approx(0.75)


def test_unknown_identifiers_resolve_to_none() -> None:
    idx = _index()
    assert idx.permno_for_gvkey("XXXXXX", date(2020, 1, 2)) is None
    assert idx.gvkey_for_permno(-1, date(2020, 1, 2)) is None


def test_empty_index_is_safe() -> None:
    idx = CCMLinkIndex.from_rows([])
    assert idx.usable == 0
    assert idx.usable_fraction == 0.0
    assert idx.permno_for_gvkey("001690", date(2020, 1, 2)) is None
