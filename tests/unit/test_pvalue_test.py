"""Unit tests for the MadEvolve-style multiple-testing guard."""

from __future__ import annotations

import pytest
from src.signals.validation.ic_calculator import ICReport
from src.signals.validation.pvalue_test import (
    expected_max_standard_normal,
    guard_from_report,
    multiple_testing_guard,
)


# ----------------------------------------------- expected_max_standard_normal
def test_expected_max_single_trial_is_zero() -> None:
    assert expected_max_standard_normal(1) == 0.0


def test_expected_max_increases_with_trials() -> None:
    assert (
        expected_max_standard_normal(2)
        < expected_max_standard_normal(10)
        < expected_max_standard_normal(100)
    )


def test_expected_max_magnitude_is_reasonable() -> None:
    # E[max] of 100 standard normals is ~2.5; the asymptotic gives ~2.36.
    assert 2.0 < expected_max_standard_normal(100) < 2.8


def test_expected_max_rejects_zero_trials() -> None:
    with pytest.raises(ValueError, match="n_trials"):
        expected_max_standard_normal(0)


# -------------------------------------------------- multiple_testing_guard
def test_strong_signal_passes() -> None:
    result = multiple_testing_guard(
        mean_ic=0.05,
        ic_std=0.05,
        n_periods=100,
        raw_p_value=1e-6,
        n_trials=10,
    )
    assert result.passed is True
    assert result.adjusted_p_value == pytest.approx(1e-5)
    assert result.expected_max_ic < result.actual_ic


def test_lucky_signal_fails_both_checks() -> None:
    result = multiple_testing_guard(
        mean_ic=0.005,
        ic_std=0.05,
        n_periods=100,
        raw_p_value=0.04,
        n_trials=50,
    )
    assert result.passed is False
    # raw_p * n_trials saturates at 1.0
    assert result.adjusted_p_value == 1.0
    assert "Bonferroni" in result.reason or "expected-max-IC" in result.reason


def test_negative_ic_never_passes() -> None:
    result = multiple_testing_guard(
        mean_ic=-0.05,
        ic_std=0.05,
        n_periods=100,
        raw_p_value=1e-9,
        n_trials=1,
    )
    assert result.passed is False
    assert "not positive" in result.reason


def test_guard_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError, match="n_trials"):
        multiple_testing_guard(0.05, 0.05, 100, 0.01, n_trials=0)
    with pytest.raises(ValueError, match="n_periods"):
        multiple_testing_guard(0.05, 0.05, 0, 0.01, n_trials=5)


def test_guard_from_report_matches_direct_call() -> None:
    report = ICReport(
        mean_ic=0.05,
        ic_std=0.05,
        icir=1.0,
        t_statistic=10.0,
        p_value=1e-6,
        positive_ic_ratio=0.7,
        n_periods=100,
        by_regime={},
    )
    from_report = guard_from_report(report, n_trials=10)
    direct = multiple_testing_guard(
        mean_ic=0.05, ic_std=0.05, n_periods=100, raw_p_value=1e-6, n_trials=10
    )
    assert from_report == direct
