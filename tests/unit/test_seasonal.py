"""Unit tests for the annual formation/holding backtest harness.

The harness answers one question per year: rank the universe on a signal at formation,
go long the bottom quintile and short the top, and measure what the spread earned over
the holding period — net of the stated cost assumption.

Every rule below exists to stop a specific way of flattering the result: quintiles must
be formed on formation-date information only, names without a full holding-period return
must not be silently dropped in a way that favours survivors, and costs must be charged
on both legs of a round trip.
"""

from __future__ import annotations

import pytest
from src.backtest.seasonal import (
    ROUND_TRIP_COST,
    AnnualResult,
    quintile_split,
    run_annual_spread,
    spread_return,
)


def _signals(n: int = 10) -> dict[int, float]:
    # permno -> signal; lower = bigger loser.
    return {i: float(i) for i in range(1, n + 1)}


# ------------------------------------------------------------------------- quintiles


def test_quintiles_split_bottom_and_top() -> None:
    longs, shorts = quintile_split(_signals(10))
    assert longs == [1, 2]  # bottom quintile = biggest losers
    assert shorts == [9, 10]  # top quintile = biggest winners


def test_quintiles_are_disjoint() -> None:
    longs, shorts = quintile_split(_signals(50))
    assert set(longs).isdisjoint(shorts)
    assert len(longs) == len(shorts) == 10


def test_too_few_names_yields_no_position() -> None:
    # With a handful of names a "quintile" is one stock; refuse rather than pretend.
    assert quintile_split(_signals(4)) == ([], [])


def test_ties_do_not_duplicate_a_name() -> None:
    longs, shorts = quintile_split(dict.fromkeys(range(1, 11), 0.0))
    assert set(longs).isdisjoint(shorts)


# ------------------------------------------------------------------- spread return


def test_long_short_spread_is_the_difference_of_leg_averages() -> None:
    rets = {1: 0.10, 2: 0.20, 9: -0.05, 10: 0.05}
    gross = spread_return([1, 2], [9, 10], rets, cost=0.0)
    assert gross == pytest.approx(0.15 - 0.0)  # long avg 0.15, short avg 0.00


def test_cost_is_charged_once_per_round_trip() -> None:
    rets = {1: 0.10, 2: 0.10, 9: 0.0, 10: 0.0}
    gross = spread_return([1, 2], [9, 10], rets, cost=0.0)
    net = spread_return([1, 2], [9, 10], rets, cost=0.003)
    assert gross - net == pytest.approx(0.003)


def test_default_cost_is_the_stated_assumption() -> None:
    assert pytest.approx(0.0030) == ROUND_TRIP_COST  # 30 bps


def test_names_without_a_holding_return_are_excluded_from_both_legs() -> None:
    # A delisted name with no return must not silently become a zero.
    rets = {1: 0.10, 9: -0.10}
    result = spread_return([1, 2], [9, 10], rets, cost=0.0)
    assert result == pytest.approx(0.20)  # computed on the names that have data


def test_an_empty_leg_yields_no_result() -> None:
    assert spread_return([], [9, 10], {9: 0.1, 10: 0.1}, cost=0.0) is None


# ---------------------------------------------------------------------- annual run


def test_annual_result_reports_both_legs_and_breadth() -> None:
    result = run_annual_spread(
        year=1995,
        signals=_signals(10),
        holding_returns={i: 0.01 * i for i in range(1, 11)},
        cost=0.0,
    )
    assert isinstance(result, AnnualResult)
    assert result.year == 1995
    assert result.n_long == 2
    assert result.n_short == 2
    assert result.long_return == pytest.approx(0.015)
    assert result.short_return == pytest.approx(0.095)
    assert result.net_return == pytest.approx(0.015 - 0.095)


def test_annual_run_returns_none_when_the_universe_is_too_thin() -> None:
    assert run_annual_spread(year=1995, signals=_signals(3), holding_returns={}, cost=0.0) is None


def test_annual_run_charges_the_cost() -> None:
    with_cost = run_annual_spread(
        year=1995,
        signals=_signals(10),
        holding_returns={i: 0.0 for i in range(1, 11)},
        cost=0.003,
    )
    assert with_cost is not None
    assert with_cost.net_return == pytest.approx(-0.003)
