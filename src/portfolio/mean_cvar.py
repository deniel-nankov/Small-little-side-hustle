"""Exact mean-CVaR portfolio optimization via the Rockafellar-Uryasev LP (Stage 5, #11).

Replaces the `vol_scaled_score_tilt` heuristic with the true minimum-CVaR optimum. For a
set of scenario returns ``r_s`` (s = 1..S), confidence ``beta``, and weights ``w``, CVaR of
the loss ``-r_s . w`` is (Rockafellar & Uryasev, 2000)::

    CVaR = min over (alpha, u>=0) of  alpha + 1/((1-beta)*S) * sum_s u_s
           s.t.  u_s >= -(r_s . w) - alpha

We minimise ``CVaR - risk_aversion * (mu . w)`` (a point on the mean-CVaR frontier) subject
to per-name caps, gross-leverage, and dollar-neutrality. Gross/L1 is linearised with the
long/short split ``w = w+ - w-`` (w+, w- >= 0). Solved with SciPy's HiGHS LP backend.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from scipy.optimize import linprog

from src.monitoring.logger import get_logger

_log = get_logger(__name__)

#: Default CVaR confidence level.
CVAR_BETA = 0.95

#: Default return-vs-CVaR trade-off weight (0 = pure min-CVaR; larger = more return-seeking).
DEFAULT_RISK_AVERSION = 1.0


class InfeasiblePortfolioError(RuntimeError):
    """Raised when the mean-CVaR LP has no optimal solution."""


def solve_mean_cvar(
    expected_returns: Mapping[str, float],
    scenarios: Sequence[Mapping[str, float]],
    *,
    max_position: float,
    max_gross: float,
    dollar_neutral: bool = True,
    cvar_beta: float = CVAR_BETA,
    risk_aversion: float = DEFAULT_RISK_AVERSION,
) -> dict[str, float]:
    """Solve the mean-CVaR LP for optimal weights.

    Args:
        expected_returns: ``ticker`` -> expected return (defines the optimisation universe).
        scenarios: Historical/simulated ``ticker`` -> return cross-sections (the CVaR sample).
        max_position: Per-name absolute weight cap.
        max_gross: Maximum gross exposure (sum of absolute weights).
        dollar_neutral: If True, constrain the net exposure to exactly zero.
        cvar_beta: CVaR confidence level.
        risk_aversion: Weight on the expected-return reward term (>= 0).

    Returns:
        ``ticker`` -> optimal weight (empty if no tickers).

    Raises:
        ValueError: if there are no scenarios.
        InfeasiblePortfolioError: if the LP has no optimal solution.
    """
    tickers = sorted(expected_returns)
    n = len(tickers)
    if n == 0:
        return {}
    n_scen = len(scenarios)
    if n_scen == 0:
        raise ValueError("mean-CVaR requires at least one scenario")

    mu = [expected_returns[t] for t in tickers]
    returns = [[float(sc.get(t, 0.0)) for t in tickers] for sc in scenarios]

    # Variables x = [ w+ (n), w- (n), alpha (1), u (S) ];  w = w+ - w-.
    idx_alpha = 2 * n
    idx_u0 = 2 * n + 1
    n_vars = 2 * n + 1 + n_scen
    cvar_coef = 1.0 / ((1.0 - cvar_beta) * n_scen)

    # Objective: minimise  alpha + cvar_coef * sum(u)  -  risk_aversion * (mu . w).
    cost = [0.0] * n_vars
    for i in range(n):
        cost[i] = -risk_aversion * mu[i]
        cost[n + i] = risk_aversion * mu[i]
    cost[idx_alpha] = 1.0
    for s in range(n_scen):
        cost[idx_u0 + s] = cvar_coef

    a_ub: list[list[float]] = []
    b_ub: list[float] = []
    # CVaR: -(r_s . (w+ - w-)) - alpha - u_s <= 0  for each scenario.
    for s in range(n_scen):
        row = [0.0] * n_vars
        for i in range(n):
            row[i] = -returns[s][i]
            row[n + i] = returns[s][i]
        row[idx_alpha] = -1.0
        row[idx_u0 + s] = -1.0
        a_ub.append(row)
        b_ub.append(0.0)
    # Gross: sum(w+ + w-) <= max_gross.
    gross_row = [0.0] * n_vars
    for i in range(n):
        gross_row[i] = 1.0
        gross_row[n + i] = 1.0
    a_ub.append(gross_row)
    b_ub.append(max_gross)

    a_eq: list[list[float]] | None = None
    b_eq: list[float] | None = None
    if dollar_neutral:
        neutral_row = [0.0] * n_vars
        for i in range(n):
            neutral_row[i] = 1.0
            neutral_row[n + i] = -1.0
        a_eq = [neutral_row]
        b_eq = [0.0]

    bounds: list[tuple[float | None, float | None]] = (
        [(0.0, max_position)] * (2 * n) + [(None, None)] + [(0.0, None)] * n_scen
    )

    result = linprog(
        c=cost, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs"
    )
    if not result.success:
        raise InfeasiblePortfolioError(str(result.message))

    solution = result.x
    weights = {tickers[i]: float(solution[i] - solution[n + i]) for i in range(n)}
    _log.info(
        "mean_cvar.solved",
        names=n,
        scenarios=n_scen,
        gross=round(sum(abs(w) for w in weights.values()), 4),
    )
    return weights
