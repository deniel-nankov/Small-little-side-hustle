"""Unit tests for the supply-chain contagion signal."""

from __future__ import annotations

from datetime import date

import pytest
from src.data.contracts.schemas import Relationship, SupplyChainLink
from src.data.source import FixtureSource
from src.signals.construction.supply_chain_signal import compute_supply_chain_signal

from tests.synth import business_days, flat_bar


def _link(ticker: str, related: str, weight: float = 1.0) -> SupplyChainLink:
    return SupplyChainLink(
        ticker=ticker,
        related_ticker=related,
        relationship=Relationship.supplier,
        weight=weight,
        is_point_in_time=True,
    )


def _build_prices() -> tuple[list, date]:
    days = business_days(date(2026, 1, 1), 30)
    prices = []
    for k, day in enumerate(days):
        prices.append(flat_bar("UP", day, 100.0 * (1.01**k)))  # rising
        prices.append(flat_bar("DOWN", day, 100.0 * (0.99**k)))  # falling
    return prices, days[-1]


def test_subject_linked_to_riser_ranks_above_subject_linked_to_faller() -> None:
    prices, as_of = _build_prices()
    links = [_link("A", "UP"), _link("C", "DOWN")]
    scores = {s.ticker: s for s in compute_supply_chain_signal(links, prices, as_of=as_of)}
    assert scores["A"].rank_score > scores["C"].rank_score


def test_subject_without_priced_related_is_excluded() -> None:
    prices, as_of = _build_prices()
    links = [_link("A", "UP"), _link("B", "NOPRICE")]
    tickers = {s.ticker for s in compute_supply_chain_signal(links, prices, as_of=as_of)}
    assert tickers == {"A"}


def test_non_point_in_time_link_raises() -> None:
    prices, as_of = _build_prices()
    bad = _link("A", "UP").model_copy(update={"is_point_in_time": False})
    with pytest.raises(ValueError, match="point-in-time"):
        compute_supply_chain_signal([bad], prices, as_of=as_of)


def test_nonpositive_lookback_raises() -> None:
    prices, as_of = _build_prices()
    with pytest.raises(ValueError, match="lookback_days"):
        compute_supply_chain_signal([], prices, as_of=as_of, lookback_days=0)


def test_runs_on_fixture_source() -> None:
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "META"]
    start, end = date(2026, 1, 1), date(2026, 4, 1)
    source = FixtureSource()
    prices = source.get_prices(tickers, start, end)
    links = source.get_supply_chain(tickers)
    scores = compute_supply_chain_signal(links, prices, as_of=end)
    assert scores
    assert all(0.0 <= s.rank_score <= 1.0 for s in scores)
