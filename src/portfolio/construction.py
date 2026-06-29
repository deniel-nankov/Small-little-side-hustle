"""Portfolio construction -> PortfolioWeights (Milestone 5).

Builds a dollar-neutral, gross-capped long/short book by tilting on the combined signal,
scaled by each name's inverse volatility (risk-adjusted alpha), then projecting onto the
constraint set. Expected return and CVaR are reported from the historical scenario set.

This is the dependency-free construction (``construction_method="vol_scaled_score_tilt"``).
The exact mean-CVaR optimum is the Rockafellar-Uryasev linear program::

    minimize   alpha + 1 / ((1 - beta) * |S|) * sum_s u_s
    subject to u_s >= -(r_s . w) - alpha,   u_s >= 0
               w . mu >= target_return
               <position / gross / neutrality constraints>

which we solve with cvxpy / NVIDIA cuOpt once those numeric dependencies are available. The
construction below respects the same constraints and reports the realized CVaR of its
weights, so the contract and downstream code are identical when the LP is swapped in.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date

from src.data.contracts.schemas import PortfolioWeights, PriceData, SignalScore
from src.monitoring.logger import get_logger
from src.portfolio import risk
from src.portfolio.constraints import PortfolioConstraints, enforce, turnover
from src.signals.construction._common import zscore

_log = get_logger(__name__)

CONSTRUCTION_METHOD = "vol_scaled_score_tilt"

#: Trailing window (observations) for per-name volatility and the CVaR scenario set.
VOL_LOOKBACK_DAYS = 63

#: Smallest volatility used in inverse-vol scaling (avoids division blow-ups).
DEFAULT_VOL_FLOOR = 1e-4

#: Module-level default so it is not constructed in the function signature (ruff B008).
DEFAULT_CONSTRAINTS = PortfolioConstraints()


def _trailing_vols(
    prices: Sequence[PriceData], as_of: date, lookback_days: int
) -> dict[str, float]:
    """Trailing return volatility per ticker over ``lookback_days`` ending on/before ``as_of``."""
    by_ticker: dict[str, list[PriceData]] = defaultdict(list)
    for bar in prices:
        if bar.date <= as_of:
            by_ticker[bar.ticker].append(bar)
    vols: dict[str, float] = {}
    for ticker, bars in by_ticker.items():
        bars.sort(key=lambda b: b.date)
        returns = [
            bars[i].adjusted_close / bars[i - 1].adjusted_close - 1.0 for i in range(1, len(bars))
        ][-lookback_days:]
        if len(returns) >= 2:
            vols[ticker] = statistics.pstdev(returns)
    return vols


def construct_portfolio(
    combined_scores: Sequence[SignalScore],
    prices: Sequence[PriceData],
    as_of: date,
    constraints: PortfolioConstraints = DEFAULT_CONSTRAINTS,
    vol_lookback_days: int = VOL_LOOKBACK_DAYS,
    prev_weights: Mapping[str, float] | None = None,
    cvar_beta: float = risk.CVAR_BETA,
) -> PortfolioWeights:
    """Construct target weights for ``as_of`` from the combined signal.

    Args:
        combined_scores: Combined signal scores (must include the ``as_of`` cross-section).
        prices: Price bars for volatility and the CVaR scenario set.
        as_of: Rebalance date.
        constraints: Position / gross / neutrality limits.
        vol_lookback_days: Trailing window for volatility and scenarios.
        prev_weights: Previous book, for turnover (``None`` = flat).
        cvar_beta: CVaR confidence level.

    Returns:
        A :class:`PortfolioWeights` for ``as_of``.

    Raises:
        ValueError: if there are no combined scores on ``as_of``.
    """
    day_scores = [s for s in combined_scores if s.date == as_of]
    if not day_scores:
        raise ValueError(f"no combined scores on {as_of}")

    tickers = sorted({s.ticker for s in day_scores})
    raw_by_ticker = {s.ticker: s.raw_score for s in day_scores}
    standardized = zscore([raw_by_ticker[t] for t in tickers])

    vols = _trailing_vols(prices, as_of, vol_lookback_days)
    positive_vols = [v for v in vols.values() if v > 0]
    median_vol = statistics.median(positive_vols) if positive_vols else DEFAULT_VOL_FLOOR

    raw_weights: dict[str, float] = {}
    for i, ticker in enumerate(tickers):
        vol = max(vols.get(ticker, median_vol) or median_vol, DEFAULT_VOL_FLOOR)
        raw_weights[ticker] = standardized[i] / vol

    weights = enforce(raw_weights, constraints)

    scenarios = risk.build_scenarios(prices, as_of, vol_lookback_days)
    portfolio_returns = risk.portfolio_scenario_returns(weights, scenarios)
    expected_return = statistics.fmean(portfolio_returns) if portfolio_returns else 0.0
    expected_cvar = risk.conditional_value_at_risk(portfolio_returns, cvar_beta)

    result = PortfolioWeights(
        date=as_of,
        weights=weights,
        expected_return=expected_return,
        expected_cvar=expected_cvar,
        turnover=turnover(weights, prev_weights),
        construction_method=CONSTRUCTION_METHOD,
    )
    _log.info(
        "portfolio.constructed",
        date=str(as_of),
        names=len(weights),
        gross=round(sum(abs(w) for w in weights.values()), 4),
        expected_cvar=round(expected_cvar, 4),
    )
    return result
