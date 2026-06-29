"""Point-in-time backtest with cost model, returning BacktestResult (Milestone 3).

Orchestrates the validation suite for one signal and packages the outcome into a
:class:`BacktestResult` (the contract that CI's ``signal_validation.yml`` consumes and that
the registry stores).

Tests run here:

* #1 IC, #2 ICIR, #3 p-value guard, #4 decay, #5 regime — always run; they need only the
  signal and prices.
* #6 correlation vs. existing signals — run only when ``existing_signals`` is supplied.
* #7 sector-neutrality — run only when ``sectors`` is supplied.

A long/short tercile portfolio (top minus bottom by score, with a coarse per-period cost)
provides the return-based statistics (annualized return, Sharpe, max drawdown). All
thresholds are named constants on :class:`ValidationThresholds` (PRINCIPLES.md Rule 1).
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from src.data.contracts.schemas import BacktestResult, PriceData, SignalScore
from src.monitoring.logger import get_logger
from src.signals.validation.decay_tester import DECAY_HORIZON_DAYS, DECAY_IC_THRESHOLD, decay_test
from src.signals.validation.ic_calculator import (
    DEFAULT_FORWARD_HORIZON_DAYS,
    MIN_CROSS_SECTION_SIZE,
    compute_forward_returns,
    daily_ics,
    evaluate_signal,
    spearman_ic,
)
from src.signals.validation.pvalue_test import multiple_testing_guard
from src.signals.validation.regime_tester import MIN_REGIMES_POSITIVE, regime_test

_log = get_logger(__name__)

#: Trading periods per year, for annualization.
PERIODS_PER_YEAR = 252

#: Forward horizon (observations) for the long/short portfolio return series.
PORTFOLIO_HORIZON_DAYS = 1

#: Fraction of names taken as the long (and short) leg of the tercile portfolio.
QUANTILE_FRACTION = 1 / 3

#: Coarse round-trip transaction cost charged per rebalance period, in basis points.
COST_PER_PERIOD_BPS = 1.0


@dataclass(frozen=True)
class ValidationThresholds:
    """Named acceptance thresholds for the 7-test validation suite (see docs/TESTING.md)."""

    ic_acceptance: float = 0.015
    icir_min: float = 0.5
    alpha: float = 0.05
    decay_horizon_days: int = DECAY_HORIZON_DAYS
    decay_ic_min: float = DECAY_IC_THRESHOLD
    min_regimes_positive: int = MIN_REGIMES_POSITIVE
    max_correlation: float = 0.5
    min_cross_section: int = MIN_CROSS_SECTION_SIZE


DEFAULT_THRESHOLDS = ValidationThresholds()


def _long_short_returns(
    scores: Sequence[SignalScore],
    forward_returns: Mapping[tuple[str, date], float],
    fraction: float,
    min_cross_section: int,
    cost_bps: float,
) -> list[float]:
    """Per-period return of a top-minus-bottom tercile long/short portfolio."""
    by_date: dict[date, list[tuple[str, float]]] = defaultdict(list)
    for score in scores:
        if (score.ticker, score.date) in forward_returns:
            by_date[score.date].append((score.ticker, score.raw_score))

    cost = cost_bps / 10_000.0
    out: list[float] = []
    for day in sorted(by_date):
        rows = by_date[day]
        if len(rows) < min_cross_section:
            continue
        rows.sort(key=lambda r: r[1])
        k = max(1, int(len(rows) * fraction))
        shorts = rows[:k]
        longs = rows[-k:]
        long_ret = statistics.fmean(forward_returns[(t, day)] for t, _ in longs)
        short_ret = statistics.fmean(forward_returns[(t, day)] for t, _ in shorts)
        out.append(long_ret - short_ret - cost)
    return out


def _portfolio_stats(returns: Sequence[float]) -> tuple[float, float, float]:
    """Return (annualized_return, sharpe_ratio, max_drawdown) for a return series."""
    if not returns:
        return 0.0, 0.0, 0.0
    mean = statistics.fmean(returns)
    std = statistics.stdev(returns) if len(returns) >= 2 else 0.0
    annualized = mean * PERIODS_PER_YEAR
    sharpe = (mean / std) * math.sqrt(PERIODS_PER_YEAR) if std > 0 else 0.0

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for r in returns:
        equity *= 1.0 + r
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity / peak - 1.0)
    return annualized, sharpe, max_drawdown


def _max_abs_correlation(
    scores: Sequence[SignalScore],
    existing_signals: Mapping[str, Sequence[SignalScore]],
    min_cross_section: int,
) -> float | None:
    """Largest mean |Spearman| between this signal and any existing signal, or None."""
    this_by_date: dict[date, dict[str, float]] = defaultdict(dict)
    for score in scores:
        this_by_date[score.date][score.ticker] = score.raw_score

    worst: float | None = None
    for other_scores in existing_signals.values():
        other_by_date: dict[date, dict[str, float]] = defaultdict(dict)
        for score in other_scores:
            other_by_date[score.date][score.ticker] = score.raw_score

        per_date: list[float] = []
        for day, this_map in this_by_date.items():
            other_map = other_by_date.get(day)
            if not other_map:
                continue
            common = sorted(set(this_map) & set(other_map))
            if len(common) < min_cross_section:
                continue
            try:
                ic = spearman_ic([this_map[t] for t in common], [other_map[t] for t in common])
            except ValueError:
                continue
            per_date.append(abs(ic))
        if per_date:
            mean_corr = statistics.fmean(per_date)
            worst = mean_corr if worst is None else max(worst, mean_corr)
    return worst


def _sector_neutral_ic(
    scores: Sequence[SignalScore],
    forward_returns: Mapping[tuple[str, date], float],
    sectors: Mapping[str, str],
    min_cross_section: int,
) -> float | None:
    """Mean IC of the signal after removing within-sector means each date, or None."""
    by_date: dict[date, list[SignalScore]] = defaultdict(list)
    for score in scores:
        by_date[score.date].append(score)

    neutral: list[SignalScore] = []
    for day_scores in by_date.values():
        sector_values: dict[str, list[float]] = defaultdict(list)
        for score in day_scores:
            sector = sectors.get(score.ticker)
            if sector is not None:
                sector_values[sector].append(score.raw_score)
        sector_mean = {sec: statistics.fmean(vals) for sec, vals in sector_values.items()}
        for score in day_scores:
            sector = sectors.get(score.ticker)
            if sector is None:
                continue
            neutral.append(
                score.model_copy(update={"raw_score": score.raw_score - sector_mean[sector]})
            )

    series = daily_ics(neutral, forward_returns, min_cross_section)
    if not series:
        return None
    return statistics.fmean(ic for _, ic in series)


def run_backtest(
    scores: Sequence[SignalScore],
    prices: Sequence[PriceData],
    n_trials: int = 1,
    sectors: Mapping[str, str] | None = None,
    existing_signals: Mapping[str, Sequence[SignalScore]] | None = None,
    thresholds: ValidationThresholds = DEFAULT_THRESHOLDS,
) -> BacktestResult:
    """Run the validation suite for one signal and return a :class:`BacktestResult`.

    Args:
        scores: The signal's scores across tickers and dates.
        prices: Price bars for the same universe (forward returns + regimes + portfolio).
        n_trials: How many candidate signals were tested to find this one (p-value guard).
        sectors: Optional ``ticker`` -> sector map; enables the sector-neutrality test (#7).
        existing_signals: Optional ``name`` -> scores; enables the correlation test (#6).
        thresholds: Acceptance thresholds.

    Returns:
        A :class:`BacktestResult` with IC/return statistics and pass/fail with reasons.

    Raises:
        ValueError: if ``scores`` is empty or no date had a computable IC.
    """
    if not scores:
        raise ValueError("no scores provided")

    fr_primary = compute_forward_returns(prices, DEFAULT_FORWARD_HORIZON_DAYS)
    report = evaluate_signal(scores, fr_primary, min_cross_section=thresholds.min_cross_section)

    fr_portfolio = compute_forward_returns(prices, PORTFOLIO_HORIZON_DAYS)
    portfolio_returns = _long_short_returns(
        scores, fr_portfolio, QUANTILE_FRACTION, thresholds.min_cross_section, COST_PER_PERIOD_BPS
    )
    annualized, sharpe, max_drawdown = _portfolio_stats(portfolio_returns)

    decay = decay_test(
        scores,
        prices,
        thresholds.decay_horizon_days,
        thresholds.decay_ic_min,
        thresholds.min_cross_section,
    )
    regime = regime_test(
        scores, fr_primary, prices, thresholds.min_regimes_positive, thresholds.min_cross_section
    )
    guard = multiple_testing_guard(
        report.mean_ic, report.ic_std, report.n_periods, report.p_value, n_trials, thresholds.alpha
    )

    failures: list[str] = []
    if report.mean_ic <= thresholds.ic_acceptance:
        failures.append(f"#1 IC {report.mean_ic:.4f} <= {thresholds.ic_acceptance}")
    if report.icir <= thresholds.icir_min:
        failures.append(f"#2 ICIR {report.icir:.4f} <= {thresholds.icir_min}")
    if not guard.passed:
        failures.append(f"#3 p-value guard: {guard.reason}")
    if not decay.passed:
        failures.append(f"#4 decay IC {decay.mean_ic:.4f} <= {decay.threshold}")
    if not regime.passed:
        failures.append(f"#5 regime: only {regime.n_positive}/4 regimes positive")
    if existing_signals:
        correlation = _max_abs_correlation(scores, existing_signals, thresholds.min_cross_section)
        if correlation is not None and correlation >= thresholds.max_correlation:
            failures.append(f"#6 correlation {correlation:.3f} >= {thresholds.max_correlation}")
    if sectors:
        neutral_ic = _sector_neutral_ic(scores, fr_primary, sectors, thresholds.min_cross_section)
        if neutral_ic is not None and neutral_ic <= thresholds.ic_acceptance:
            failures.append(f"#7 sector-neutral IC {neutral_ic:.4f} <= {thresholds.ic_acceptance}")

    dates = [score.date for score in scores]
    result = BacktestResult(
        signal_name=scores[0].signal_name,
        start_date=min(dates),
        end_date=max(dates),
        mean_ic=report.mean_ic,
        ic_std=report.ic_std,
        icir=report.icir,
        t_statistic=report.t_statistic,
        p_value=report.p_value,
        positive_ic_ratio=report.positive_ic_ratio,
        annualized_return=annualized,
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe,
        regime_results=regime.by_regime,
        passed_validation=not failures,
        failure_reasons=failures,
    )
    _log.info(
        "backtest.complete",
        signal=result.signal_name,
        mean_ic=round(result.mean_ic, 4),
        passed=result.passed_validation,
        n_failures=len(failures),
    )
    return result
