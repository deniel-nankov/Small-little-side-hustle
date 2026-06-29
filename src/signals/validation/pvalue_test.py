"""MadEvolve-style p-hacking guard (Milestone 3).

When many candidate signals are tested, the best one's IC is inflated by selection. This
module asks: is the chosen signal's IC significantly higher than what the *best of N random
signals* would produce by chance?

Two complementary checks, both reported:

* **Bonferroni** — multiply the signal's raw p-value by the number of trials and compare to
  alpha. The rigorous, conservative multiple-testing correction.
* **Expected-max-IC ceiling** — the IC you would expect the best of N random signals to
  reach (order statistics of N standard normals scaled by the IC standard error). Intuitive
  framing of the same idea.

A signal passes only if it clears *both* (and its IC is positive).
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field

from src.signals.validation.ic_calculator import ICReport

#: Significance level for the Bonferroni-corrected p-value.
DEFAULT_ALPHA = 0.05


class MultipleTestingResult(BaseModel):
    """Outcome of the multiple-testing guard for one candidate signal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actual_ic: float
    n_trials: int = Field(ge=1)
    ic_standard_error: float = Field(ge=0)
    expected_max_ic: float
    raw_p_value: float = Field(ge=0, le=1)
    adjusted_p_value: float = Field(ge=0, le=1)
    alpha: float = Field(gt=0, lt=1)
    passed: bool
    reason: str


def expected_max_standard_normal(n_trials: int) -> float:
    """Approximate E[max] of ``n_trials`` i.i.d. standard normal draws.

    Uses the classical extreme-value asymptotic; exact for the degenerate single-trial case.

    Args:
        n_trials: Number of independent trials (>= 1).

    Returns:
        The expected maximum (0.0 for a single trial).

    Raises:
        ValueError: if ``n_trials`` < 1.
    """
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")
    if n_trials == 1:
        return 0.0
    ln_n = math.log(n_trials)
    root = math.sqrt(2.0 * ln_n)
    return root - (math.log(ln_n) + math.log(4.0 * math.pi)) / (2.0 * root)


def multiple_testing_guard(
    mean_ic: float,
    ic_std: float,
    n_periods: int,
    raw_p_value: float,
    n_trials: int,
    alpha: float = DEFAULT_ALPHA,
) -> MultipleTestingResult:
    """Decide whether ``mean_ic`` survives correction for having tested ``n_trials`` signals.

    Args:
        mean_ic: The candidate signal's mean IC.
        ic_std: Standard deviation of its IC time series.
        n_periods: Number of IC observations (periods).
        raw_p_value: The signal's uncorrected two-sided p-value.
        n_trials: How many candidate signals were tested to find this one.
        alpha: Significance level.

    Returns:
        A :class:`MultipleTestingResult` with both checks and the final pass/fail.

    Raises:
        ValueError: if ``n_trials`` < 1 or ``n_periods`` < 1.
    """
    if n_trials < 1:
        raise ValueError(f"n_trials must be >= 1, got {n_trials}")
    if n_periods < 1:
        raise ValueError(f"n_periods must be >= 1, got {n_periods}")

    ic_se = ic_std / math.sqrt(n_periods)
    expected_max_ic = ic_se * expected_max_standard_normal(n_trials)
    adjusted_p = min(1.0, raw_p_value * n_trials)

    passes_bonferroni = adjusted_p < alpha
    beats_ceiling = mean_ic > expected_max_ic
    positive = mean_ic > 0
    passed = passes_bonferroni and beats_ceiling and positive

    if passed:
        reason = "IC clears the Bonferroni p-value and the expected-max-IC ceiling"
    else:
        failures: list[str] = []
        if not positive:
            failures.append("IC is not positive")
        if not passes_bonferroni:
            failures.append(f"Bonferroni p={adjusted_p:.4g} >= alpha={alpha}")
        if not beats_ceiling:
            failures.append(f"IC {mean_ic:.4g} <= expected-max-IC {expected_max_ic:.4g}")
        reason = "; ".join(failures)

    return MultipleTestingResult(
        actual_ic=mean_ic,
        n_trials=n_trials,
        ic_standard_error=ic_se,
        expected_max_ic=expected_max_ic,
        raw_p_value=raw_p_value,
        adjusted_p_value=adjusted_p,
        alpha=alpha,
        passed=passed,
        reason=reason,
    )


def guard_from_report(
    report: ICReport, n_trials: int, alpha: float = DEFAULT_ALPHA
) -> MultipleTestingResult:
    """Run :func:`multiple_testing_guard` directly from an :class:`ICReport`.

    Args:
        report: The signal's IC report.
        n_trials: How many candidate signals were tested.
        alpha: Significance level.

    Returns:
        A :class:`MultipleTestingResult`.
    """
    return multiple_testing_guard(
        mean_ic=report.mean_ic,
        ic_std=report.ic_std,
        n_periods=report.n_periods,
        raw_p_value=report.p_value,
        n_trials=n_trials,
        alpha=alpha,
    )
