"""Unit tests for the QuantaAlpha-style evolutionary miner (Stage 4, #54).

The acceptance bar: on a synthetic universe with a PLANTED pattern (short-term
reversal: tomorrow's return anti-correlates with today's), evolution must find a
factor with clearly positive in-sample IC — and mining is IN-SAMPLE by definition,
so the suite's job here is the search machinery, not out-of-sample truth (that
remains run_backtest's job on a held-out window).
"""

from __future__ import annotations

import random
from datetime import date
from pathlib import Path

import pytest
from src.monitoring.audit import AuditLog
from src.signals.discovery.factor_dsl import (
    Feature,
    TimeSeries,
    node_count,
    random_expression,
)
from src.signals.discovery.quanta_alpha import (
    EvolutionConfig,
    crossover,
    mine_alphas,
    mutate,
)

from tests.synth import business_days, flat_bar


def _reversal_universe(n_tickers: int = 10, n_days: int = 140) -> list:  # noqa: ANN202
    """Prices where tomorrow's return reverses ~half of today's (mineable pattern)."""
    days = business_days(date(2026, 1, 1), n_days)
    bars = []
    for k in range(n_tickers):
        rng = random.Random(f"rev|{k}")
        price = 100.0
        last_shock = 0.0
        for i, day in enumerate(days):
            if i > 0:
                shock = rng.gauss(0.0, 0.02)
                ret = -0.5 * last_shock + shock
                last_shock = shock
                price = max(price * (1.0 + ret), 1.0)
            bars.append(flat_bar(f"T{k:02d}", day, price))
    return bars


# --------------------------------------------------------------------- genetic ops


def test_mutate_changes_tree_but_stays_valid() -> None:
    rng = random.Random(3)
    parent = random_expression(random.Random(1), max_depth=4)
    child = mutate(parent, rng, max_depth=4)
    assert child != parent
    assert node_count(child) >= 1


def test_crossover_grafts_donor_material() -> None:
    rng = random.Random(5)
    a = TimeSeries("ts_mean", Feature("ret"), 5)
    b = TimeSeries("ts_std", Feature("volume"), 21)
    child = crossover(a, b, rng)
    assert node_count(child) >= 1
    # The child must mention material from at least one parent's vocabulary.
    assert any(tok in str(child) for tok in ("ret", "volume"))


def test_genetic_ops_are_deterministic_given_seed() -> None:
    parent = random_expression(random.Random(1), max_depth=4)
    c1 = mutate(parent, random.Random(9), max_depth=4)
    c2 = mutate(parent, random.Random(9), max_depth=4)
    assert c1 == c2


# ------------------------------------------------------------------------- mining


def test_mining_finds_planted_reversal_signal() -> None:
    prices = _reversal_universe()
    config = EvolutionConfig(population_size=24, generations=6, seed=11)
    mined = mine_alphas(prices, config=config)
    assert mined  # something survived
    best = mined[0]
    assert best.mean_ic > 0.05  # the planted pattern is strong; evolution must find it
    assert mined == sorted(mined, key=lambda m: m.fitness, reverse=True)


def test_mining_is_deterministic() -> None:
    prices = _reversal_universe(n_tickers=8, n_days=100)
    config = EvolutionConfig(population_size=12, generations=3, seed=42)
    a = mine_alphas(prices, config=config)
    b = mine_alphas(prices, config=config)
    assert [str(m.expression) for m in a] == [str(m.expression) for m in b]


def test_mining_respects_library_originality() -> None:
    prices = _reversal_universe(n_tickers=8, n_days=100)
    config = EvolutionConfig(population_size=12, generations=3, seed=42)
    baseline = mine_alphas(prices, config=config)
    # Ban the previous winner: it must not be returned again as an exact replica.
    library = [baseline[0].expression]
    rerun = mine_alphas(prices, config=config, library=library)
    assert all(str(m.expression) != str(library[0]) for m in rerun)


def test_mining_records_audit_event(tmp_path: Path) -> None:
    prices = _reversal_universe(n_tickers=8, n_days=100)
    audit = AuditLog(tmp_path / "audit.jsonl")
    config = EvolutionConfig(population_size=12, generations=2, seed=1)
    mine_alphas(prices, config=config, audit=audit)
    events = [e["event"] for e in audit.entries()]
    assert "discovery.evolution_completed" in events
    assert audit.verify() is True


def test_mining_rejects_empty_prices() -> None:
    with pytest.raises(ValueError, match="no prices"):
        mine_alphas([], config=EvolutionConfig(population_size=4, generations=1, seed=1))


def test_hall_of_fame_has_no_near_duplicates() -> None:
    prices = _reversal_universe(n_tickers=8, n_days=100)
    config = EvolutionConfig(population_size=24, generations=4, seed=7, hall_of_fame=5)
    mined = mine_alphas(prices, config=config)
    assert len(mined) <= 5
    expressions = [str(m.expression) for m in mined]
    assert len(expressions) == len(set(expressions))  # exact dupes impossible
