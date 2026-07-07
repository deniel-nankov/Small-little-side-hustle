"""AlphaAgent-style decay-resistance filter (Stage 4, #53).

Implements the regularization machinery of AlphaAgent (Tang et al., KDD 2025,
arXiv:2502.16789), which counteracts alpha decay by rejecting factors that are
derivative, over-engineered, or over-parameterized BEFORE any backtest is run:

* **Originality S(f)** — largest-common-subtree similarity against the existing factor
  library, normalized by the candidate's own size. Replicating a known factor (or
  Alpha101-style folklore already in the library) is penalized; crowded factors decay.
* **Complexity constraints** — symbolic length SL(f) (AST node count) and parameter
  count PC(f) (free windows). Over-fit expressions look great in-sample and die
  out-of-sample.
* **Parsimony** — the paper's ``log(1 + |Ff|)`` term over distinct raw features.

The paper's third regularizer, hypothesis-factor alignment C(h,d,f), needs an LLM
judge; it is deliberately omitted here and contributes nothing until the LLM client
lands (the weights dataclass reserves its slot). Decay itself is measured by the
existing validation suite (``decay_tester`` / test #4 in ``run_backtest``) — this
module is the cheap structural gate in front of it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from src.monitoring.logger import get_logger
from src.signals.discovery.factor_dsl import (
    Binary,
    Expression,
    Feature,
    TimeSeries,
    Unary,
    node_count,
    param_count,
    similarity,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.monitoring.audit import AuditLog

_log = get_logger(__name__)


@dataclass(frozen=True)
class RegularizationWeights:
    """Weights for the ER(f) penalty (paper's β1/β2/β3).

    ``alignment`` is reserved for the LLM-judged hypothesis-factor consistency term
    and is unused until the LLM client exists.
    """

    originality: float = 1.0
    alignment: float = 0.0
    parsimony: float = 1.0


DEFAULT_WEIGHTS = RegularizationWeights()


@dataclass(frozen=True)
class FilterThresholds:
    """Structural acceptance bounds (defaults sized for max_depth≈5 mining)."""

    max_similarity: float = 0.6  # originality gate: share of the tree found elsewhere
    max_nodes: int = 25  # symbolic length SL(f)
    max_params: int = 5  # parameter count PC(f)


@dataclass(frozen=True)
class FilterVerdict:
    """Outcome of the structural decay-resistance filter."""

    accepted: bool
    reasons: list[str] = field(default_factory=list)
    originality: float = 0.0
    symbolic_length: int = 0
    parameter_count: int = 0
    penalty: float = 0.0


DEFAULT_THRESHOLDS = FilterThresholds()


def feature_count(expr: Expression) -> int:
    """|Ff|: number of DISTINCT raw features the expression reads."""
    leaves: set[str] = set()

    def walk(node: Expression) -> None:
        if isinstance(node, Feature):
            leaves.add(node.name)
        elif isinstance(node, Unary | TimeSeries):
            walk(node.child)
        elif isinstance(node, Binary):
            walk(node.left)
            walk(node.right)

    walk(expr)
    return len(leaves)


def originality_penalty(expr: Expression, library: Sequence[Expression]) -> float:
    """S(f): worst-case normalized subtree overlap with the library, in [0, 1].

    Args:
        expr: Candidate factor.
        library: Existing/known factors (accepted signals, folklore alphas).

    Returns:
        ``max_j similarity(f, lib_j) / node_count(f)`` — 0 for an empty library,
        1 when the candidate fully appears in a library factor.
    """
    if not library:
        return 0.0
    own = node_count(expr)
    return max(similarity(expr, known) for known in library) / own


def regularization_penalty(
    expr: Expression,
    library: Sequence[Expression],
    *,
    weights: RegularizationWeights = DEFAULT_WEIGHTS,
) -> float:
    """ER(f) = β1·S(f) + β3·log(1 + |Ff|) (alignment term pending the LLM client).

    Args:
        expr: Candidate factor.
        library: Existing factor library.
        weights: Term weights.

    Returns:
        The penalty (higher = more derivative / less parsimonious).
    """
    return weights.originality * originality_penalty(expr, library) + (
        weights.parsimony * math.log(1 + feature_count(expr))
    )


def decay_resistance_filter(
    expr: Expression,
    *,
    library: Sequence[Expression],
    thresholds: FilterThresholds = DEFAULT_THRESHOLDS,
    weights: RegularizationWeights = DEFAULT_WEIGHTS,
    audit: AuditLog | None = None,
) -> FilterVerdict:
    """Structurally vet a candidate factor before it earns a backtest.

    Args:
        expr: Candidate factor expression.
        library: Existing factors to measure originality against.
        thresholds: Acceptance bounds.
        weights: ER(f) penalty weights (reported on the verdict for ranking).
        audit: Optional tamper-evident log; the verdict is recorded.

    Returns:
        A :class:`FilterVerdict` with per-rule failure reasons (empty = accepted).
    """
    s_f = originality_penalty(expr, library)
    sl_f = node_count(expr)
    pc_f = param_count(expr)
    reasons: list[str] = []
    if s_f > thresholds.max_similarity:
        reasons.append(
            f"originality: {s_f:.2f} of the tree already exists in the library "
            f"(max {thresholds.max_similarity:.2f})"
        )
    if sl_f > thresholds.max_nodes:
        reasons.append(f"symbolic length {sl_f} > {thresholds.max_nodes} (overfit risk)")
    if pc_f > thresholds.max_params:
        reasons.append(f"parameter count {pc_f} > {thresholds.max_params} (overfit risk)")

    verdict = FilterVerdict(
        accepted=not reasons,
        reasons=reasons,
        originality=s_f,
        symbolic_length=sl_f,
        parameter_count=pc_f,
        penalty=regularization_penalty(expr, library, weights=weights),
    )
    _log.info(
        "discovery.factor_filtered",
        accepted=verdict.accepted,
        originality=round(s_f, 3),
        nodes=sl_f,
        params=pc_f,
    )
    if audit is not None:
        audit.record(
            "discovery.factor_filtered",
            {
                "expression": str(expr),
                "accepted": verdict.accepted,
                "reasons": reasons,
                "originality": round(s_f, 4),
                "symbolic_length": sl_f,
                "parameter_count": pc_f,
            },
            actor="discovery",
        )
    return verdict
