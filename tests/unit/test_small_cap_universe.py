"""Unit tests for point-in-time small-cap universe construction.

Universe construction is where survivorship bias actually enters — CRSP itself is clean.
Every rule here is a defence against a specific way of accidentally cheating:

* market cap is computed AS OF the formation date from that date's cross-section, never
  from today's constituent list;
* ``shrout`` is in THOUSANDS in CRSP — forgetting the factor understates every market cap
  by 1000x and silently selects the wrong companies;
* size breakpoints come from NYSE names only (the academic standard), because NASDAQ's
  long tail of tiny listings would otherwise drag every breakpoint down;
* ``shrcd`` 10/11 keeps US common stock and excludes ADRs, REITs, closed-end funds.
"""

from __future__ import annotations

import pytest
from src.universe.small_cap import (
    SHROUT_MULTIPLIER,
    UniverseSpec,
    assign_decile,
    market_cap_from_row,
    nyse_breakpoints,
    select_universe,
)


def _row(permno: int, prc: float, shrout: float, hexcd: int = 1) -> dict:
    return {"permno": permno, "prc": prc, "shrout": shrout, "hexcd": hexcd}


# ---------------------------------------------------------------------- market cap


def test_shrout_is_in_thousands() -> None:
    # 1,000 (thousand) shares at $50 = 1,000,000 shares = $50M, not $50k.
    assert SHROUT_MULTIPLIER == 1000.0
    assert market_cap_from_row(_row(1, 50.0, 1000.0)) == pytest.approx(50_000_000.0)


def test_negative_price_is_absolute_valued() -> None:
    # CRSP negative prc = bid/ask midpoint; the magnitude is still the price.
    assert market_cap_from_row(_row(1, -50.0, 1000.0)) == pytest.approx(50_000_000.0)


@pytest.mark.parametrize("row", [{"prc": None, "shrout": 1000.0}, {"prc": 50.0, "shrout": None}])
def test_incomplete_rows_have_no_market_cap(row: dict) -> None:
    assert market_cap_from_row({"permno": 1, **row}) is None


def test_zero_shares_has_no_market_cap() -> None:
    assert market_cap_from_row(_row(1, 50.0, 0.0)) is None


# ---------------------------------------------------------------------- breakpoints


def test_breakpoints_use_nyse_names_only() -> None:
    # Ten NYSE names spanning $10M..$100M, plus a swarm of tiny NASDAQ names that must
    # NOT drag the breakpoints down.
    nyse = [_row(i, 10.0, i * 1000.0, hexcd=1) for i in range(1, 11)]
    nasdaq = [_row(100 + i, 1.0, 10.0, hexcd=3) for i in range(50)]
    bps = nyse_breakpoints(nyse + nasdaq)
    assert len(bps) == 9  # nine cut points make ten deciles
    assert bps == sorted(bps)
    assert min(bps) > 10_000_000.0  # a NASDAQ-contaminated breakpoint would be far lower


def test_breakpoints_need_a_real_cross_section() -> None:
    assert nyse_breakpoints([_row(1, 10.0, 1000.0)]) == []


# -------------------------------------------------------------------------- deciles


def test_decile_assignment_spans_one_to_ten() -> None:
    bps = [float(x) for x in range(10, 100, 10)]
    assert assign_decile(5.0, bps) == 1  # below every breakpoint = smallest
    assert assign_decile(95.0, bps) == 10  # above every breakpoint = largest
    assert assign_decile(45.0, bps) == 5


def test_decile_is_one_when_no_breakpoints_exist() -> None:
    assert assign_decile(100.0, []) == 1


# ------------------------------------------------------------------------ selection


def _cross_section() -> list[dict]:
    # 10 NYSE names, market caps $10M .. $100M, so deciles map one-to-one.
    return [_row(i, 10.0, i * 1000.0, hexcd=1) for i in range(1, 11)]


def _all_common() -> dict[int, int]:
    return dict.fromkeys(range(1, 200), 10)


def test_selects_only_the_requested_deciles() -> None:
    picked = select_universe(_cross_section(), _all_common(), UniverseSpec(min_price=0.0))
    assert {m.decile for m in picked} <= {6, 7, 8}
    assert picked  # non-empty


def test_price_floor_excludes_penny_names() -> None:
    rows = [*_cross_section(), _row(999, 2.0, 5000.0, hexcd=1)]
    picked = select_universe(rows, _all_common(), UniverseSpec(min_price=5.0))
    assert 999 not in {m.permno for m in picked}


def test_non_common_share_codes_are_excluded() -> None:
    # shrcd 73 = closed-end fund; 31 = REIT. Neither is US common stock.
    codes = {**_all_common(), 7: 73, 8: 31}
    picked = select_universe(_cross_section(), codes, UniverseSpec(min_price=0.0))
    assert {7, 8}.isdisjoint({m.permno for m in picked})


def test_permno_absent_from_the_share_code_map_is_excluded() -> None:
    # Unknown share class is not an invitation to guess.
    codes = {k: v for k, v in _all_common().items() if k != 7}
    picked = select_universe(_cross_section(), codes, UniverseSpec(min_price=0.0))
    assert 7 not in {m.permno for m in picked}


def test_members_carry_market_cap_and_are_sorted_by_it() -> None:
    picked = select_universe(_cross_section(), _all_common(), UniverseSpec(min_price=0.0))
    caps = [m.market_cap for m in picked]
    assert caps == sorted(caps)
    assert all(c > 0 for c in caps)


def test_empty_cross_section_yields_empty_universe() -> None:
    assert select_universe([], _all_common(), UniverseSpec()) == []
