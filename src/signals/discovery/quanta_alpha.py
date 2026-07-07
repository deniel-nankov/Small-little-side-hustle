"""QuantaAlpha-style evolutionary alpha miner (Stage 4, #54).

Evolutionary factor mining in the spirit of QuantaAlpha (arXiv:2602.07085, MIT
reference implementation) and classic genetic programming: a population of factor
expressions (see :mod:`factor_dsl`) evolves through tournament selection, subtree
mutation, and subtree crossover; fitness is in-sample mean IC minus a complexity
penalty. Every child must pass the AlphaAgent structural filter (originality vs the
library + complexity bounds) before it may enter the population — the decay-resistance
regularizers run INSIDE the search loop, not after it.

Discipline notes (non-negotiables):

* Mining is in-sample BY DEFINITION — pass TRAIN-window prices only (see
  ``src.signals.validation.splits``) and send survivors through ``run_backtest`` on a
  held-out window before believing anything. Every mined factor counts toward the
  multiple-testing budget: pass the total number of candidates evaluated as
  ``n_trials`` to the validation suite.
* Deterministic: everything derives from ``EvolutionConfig.seed``.
* ``propose`` is the LLM hook (NIM client, #52 follow-up): a callable returning
  seed expressions for the initial population. Absent an LLM, seeding is random.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.monitoring.logger import get_logger
from src.signals.discovery.alpha_agent import (
    FilterThresholds,
    decay_resistance_filter,
)
from src.signals.discovery.factor_dsl import (
    Binary,
    Expression,
    Feature,
    TimeSeries,
    Unary,
    node_count,
    panel_from_prices,
    random_expression,
    to_scores,
)
from src.signals.validation.ic_calculator import compute_forward_returns, daily_ics

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from src.data.contracts.schemas import PriceData
    from src.monitoring.audit import AuditLog

_log = get_logger(__name__)

MINED_SIGNAL_VERSION = "0.1.0"


@dataclass(frozen=True)
class EvolutionConfig:
    """Knobs for one evolutionary mining run (all determinism flows from ``seed``)."""

    population_size: int = 40
    generations: int = 8
    max_depth: int = 4
    tournament_size: int = 3
    mutation_rate: float = 0.5  # probability a child comes from mutation vs crossover
    elite_count: int = 4
    hall_of_fame: int = 10
    complexity_penalty: float = 0.002  # fitness deduction per AST node
    forward_horizon_days: int = 21
    min_cross_section: int = 5
    seed: int = 7


DEFAULT_CONFIG = EvolutionConfig()


@dataclass(frozen=True)
class MinedFactor:
    """One surviving factor with its in-sample statistics."""

    expression: Expression
    fitness: float
    mean_ic: float
    n_evaluated: int  # total candidates evaluated in the run (multiple-testing budget)


def _collect(expr: Expression) -> list[Expression]:
    """All subtrees of ``expr`` in preorder (index 0 is the root)."""
    out: list[Expression] = [expr]
    if isinstance(expr, Unary | TimeSeries):
        out.extend(_collect(expr.child))
    elif isinstance(expr, Binary):
        out.extend(_collect(expr.left))
        out.extend(_collect(expr.right))
    return out


def _replace(expr: Expression, index: int, replacement: Expression) -> Expression:
    """Return a copy of ``expr`` with the ``index``-th preorder subtree swapped out."""

    def rebuild(node: Expression, counter: list[int]) -> Expression:
        if counter[0] == index:
            counter[0] += 1
            return replacement
        counter[0] += 1
        if isinstance(node, Feature):
            return node
        if isinstance(node, Unary):
            return Unary(node.op, rebuild(node.child, counter))
        if isinstance(node, TimeSeries):
            return TimeSeries(node.op, rebuild(node.child, counter), node.window)
        return Binary(node.op, rebuild(node.left, counter), rebuild(node.right, counter))

    return rebuild(expr, [0])


def mutate(expr: Expression, rng: random.Random, *, max_depth: int = 4) -> Expression:
    """Subtree mutation: replace a random node with a fresh random expression.

    Args:
        expr: Parent expression (never modified — nodes are frozen).
        rng: Seeded random source.
        max_depth: Depth bound for the replacement subtree.

    Returns:
        A new expression differing from the parent (retries until it differs).
    """
    for _ in range(10):
        index = rng.randrange(node_count(expr))
        child = _replace(expr, index, random_expression(rng, max_depth=max_depth))
        if child != expr:
            return child
    return random_expression(rng, max_depth=max_depth)


def crossover(a: Expression, b: Expression, rng: random.Random) -> Expression:
    """Subtree crossover: graft a random subtree of ``b`` into a random site in ``a``.

    Args:
        a: Recipient expression.
        b: Donor expression.
        rng: Seeded random source.

    Returns:
        The recombined expression.
    """
    donor = rng.choice(_collect(b))
    site = rng.randrange(node_count(a))
    return _replace(a, site, donor)


def mine_alphas(
    prices: Sequence[PriceData],
    *,
    config: EvolutionConfig = DEFAULT_CONFIG,
    library: Sequence[Expression] = (),
    thresholds: FilterThresholds | None = None,
    propose: Callable[[int], Sequence[Expression]] | None = None,
    audit: AuditLog | None = None,
) -> list[MinedFactor]:
    """Evolve factor expressions against ``prices`` and return the hall of fame.

    Args:
        prices: TRAIN-window bars only (mining is in-sample; validate out-of-sample).
        config: Evolution knobs; determinism flows from ``config.seed``.
        library: Known factors — candidates too similar to these are filtered out
            (AlphaAgent originality) and exact replicas can never be returned.
        thresholds: Structural filter bounds (defaults from :mod:`alpha_agent`).
        propose: Optional LLM hook: ``propose(n)`` returns up to ``n`` seed
            expressions for the initial population (invalid ones are ignored).
        audit: Optional tamper-evident log; the run summary is recorded.

    Returns:
        Up to ``config.hall_of_fame`` unique factors sorted by fitness (descending).
        Each carries ``n_evaluated`` — pass it as ``n_trials`` to ``run_backtest``.

    Raises:
        ValueError: if ``prices`` is empty.
    """
    panel = panel_from_prices(prices)
    forward = compute_forward_returns(prices, config.forward_horizon_days)
    rng = random.Random(config.seed)
    gate = thresholds or FilterThresholds()

    fitness_cache: dict[str, tuple[float, float]] = {}

    def evaluate(expr: Expression) -> tuple[float, float]:
        key = str(expr)
        if key not in fitness_cache:
            scores = to_scores(
                expr, panel, signal_name="candidate", signal_version=MINED_SIGNAL_VERSION
            )
            series = daily_ics(scores, forward, config.min_cross_section) if scores else []
            if not series:
                fitness_cache[key] = (-math.inf, 0.0)
            else:
                mean_ic = sum(ic for _, ic in series) / len(series)
                fitness = mean_ic - config.complexity_penalty * node_count(expr)
                fitness_cache[key] = (fitness, mean_ic)
        return fitness_cache[key]

    def admissible(expr: Expression) -> bool:
        return decay_resistance_filter(expr, library=library, thresholds=gate).accepted

    population: list[Expression] = []
    if propose is not None:
        population.extend(e for e in propose(config.population_size) if admissible(e))
    while len(population) < config.population_size:
        candidate = random_expression(rng, max_depth=config.max_depth)
        if admissible(candidate):
            population.append(candidate)

    def tournament() -> Expression:
        contenders = [rng.choice(population) for _ in range(config.tournament_size)]
        return max(contenders, key=lambda e: evaluate(e)[0])

    for generation in range(config.generations):
        ranked = sorted(population, key=lambda e: evaluate(e)[0], reverse=True)
        next_population = ranked[: config.elite_count]
        while len(next_population) < config.population_size:
            if rng.random() < config.mutation_rate:
                child = mutate(tournament(), rng, max_depth=config.max_depth)
            else:
                child = crossover(tournament(), tournament(), rng)
            if admissible(child):
                next_population.append(child)
            else:  # keep the population fed even when the filter is strict
                fresh = random_expression(rng, max_depth=config.max_depth)
                if admissible(fresh):
                    next_population.append(fresh)
        population = next_population
        best_fit, best_ic = evaluate(
            max(population, key=lambda e: evaluate(e)[0])
        )
        _log.info(
            "discovery.generation",
            generation=generation + 1,
            best_fitness=round(best_fit, 4),
            best_ic=round(best_ic, 4),
            evaluated=len(fitness_cache),
        )

    n_evaluated = len(fitness_cache)
    hall: list[MinedFactor] = []
    seen: set[str] = set()
    for expr in sorted(set(population), key=lambda e: evaluate(e)[0], reverse=True):
        key = str(expr)
        if key in seen or not math.isfinite(evaluate(expr)[0]):
            continue
        seen.add(key)
        fitness, mean_ic = evaluate(expr)
        hall.append(
            MinedFactor(expression=expr, fitness=fitness, mean_ic=mean_ic, n_evaluated=n_evaluated)
        )
        if len(hall) == config.hall_of_fame:
            break

    _log.info(
        "discovery.evolution_completed",
        survivors=len(hall),
        evaluated=n_evaluated,
        best=str(hall[0].expression) if hall else None,
    )
    if audit is not None:
        audit.record(
            "discovery.evolution_completed",
            {
                "seed": config.seed,
                "generations": config.generations,
                "candidates_evaluated": n_evaluated,
                "survivors": [str(m.expression) for m in hall],
                "best_in_sample_ic": round(hall[0].mean_ic, 4) if hall else None,
            },
            actor="discovery",
        )
    return hall
