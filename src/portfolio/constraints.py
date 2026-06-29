"""Portfolio constraints: position limits, leverage, dollar-neutrality, turnover (Milestone 5).

``enforce`` projects raw target weights onto the feasible set; ``violations`` reports any
breaches of a finished weight vector (used as a safety check before trading).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

#: Maximum absolute weight per name, as a fraction of gross.
DEFAULT_MAX_POSITION = 0.10

#: Maximum gross exposure (sum of absolute weights).
DEFAULT_MAX_GROSS = 1.0


@dataclass(frozen=True)
class PortfolioConstraints:
    """Hard limits the constructed portfolio must respect."""

    max_position: float = DEFAULT_MAX_POSITION
    max_gross: float = DEFAULT_MAX_GROSS
    dollar_neutral: bool = True
    max_turnover: float = 1.0


def enforce(
    raw_weights: Mapping[str, float], constraints: PortfolioConstraints
) -> dict[str, float]:
    """Project raw target weights onto the feasible set.

    Order: dollar-neutralize -> cap each name -> rebalance long/short legs to net zero
    (by scaling the larger leg down, which never breaches a cap) -> scale gross to the limit.

    Args:
        raw_weights: Unconstrained target weights.
        constraints: The limits to enforce.

    Returns:
        A feasible ``ticker`` -> weight mapping (empty input returns empty).
    """
    if not raw_weights:
        return {}
    weights = dict(raw_weights)

    if constraints.dollar_neutral:
        mean = sum(weights.values()) / len(weights)
        weights = {t: w - mean for t, w in weights.items()}

    cap = constraints.max_position
    weights = {t: max(-cap, min(cap, w)) for t, w in weights.items()}

    if constraints.dollar_neutral:
        long_sum = sum(w for w in weights.values() if w > 0)
        short_sum = -sum(w for w in weights.values() if w < 0)
        if long_sum > 0 and short_sum > 0:
            if long_sum > short_sum:
                factor = short_sum / long_sum
                weights = {t: (w * factor if w > 0 else w) for t, w in weights.items()}
            elif short_sum > long_sum:
                factor = long_sum / short_sum
                weights = {t: (w * factor if w < 0 else w) for t, w in weights.items()}

    gross = sum(abs(w) for w in weights.values())
    if gross > constraints.max_gross and gross > 0:
        scale = constraints.max_gross / gross
        weights = {t: w * scale for t, w in weights.items()}
    return weights


def turnover(new_weights: Mapping[str, float], old_weights: Mapping[str, float] | None) -> float:
    """One-sided-agnostic L1 turnover between two weight vectors.

    Args:
        new_weights: Target weights.
        old_weights: Previous weights (``None`` treats the starting book as flat).

    Returns:
        Sum of absolute weight changes across the union of tickers.
    """
    old = dict(old_weights) if old_weights else {}
    tickers = set(new_weights) | set(old)
    return sum(abs(new_weights.get(t, 0.0) - old.get(t, 0.0)) for t in tickers)


def violations(weights: Mapping[str, float], constraints: PortfolioConstraints) -> list[str]:
    """Return a list of human-readable constraint breaches (empty if feasible).

    Args:
        weights: The weight vector to check.
        constraints: The limits.

    Returns:
        A list of violation messages; empty means the vector is feasible.
    """
    problems: list[str] = []
    for ticker, weight in weights.items():
        if abs(weight) > constraints.max_position + 1e-9:
            problems.append(
                f"{ticker} |weight| {abs(weight):.4f} > max_position {constraints.max_position}"
            )
    gross = sum(abs(w) for w in weights.values())
    if gross > constraints.max_gross + 1e-9:
        problems.append(f"gross {gross:.4f} > max_gross {constraints.max_gross}")
    if constraints.dollar_neutral:
        net = sum(weights.values())
        if abs(net) > 0.05:  # allow small residual from per-name capping
            problems.append(f"net exposure {net:.4f} not ~dollar-neutral")
    return problems
