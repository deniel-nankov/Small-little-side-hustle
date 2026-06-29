"""Unit tests for the regime-stability test."""

from __future__ import annotations

from src.signals.validation.ic_calculator import (
    DEFAULT_FORWARD_HORIZON_DAYS,
    compute_forward_returns,
)
from src.signals.validation.regime_tester import REGIMES, classify_regimes, regime_test

from tests.synth import make_noise_scores, make_predictive_universe


def test_classify_regimes_covers_all_four_labels() -> None:
    _, prices = make_predictive_universe()
    labels = classify_regimes(prices)
    seen: set[str] = set().union(*labels.values())
    assert seen == set(REGIMES)


def test_every_date_carries_a_direction_label() -> None:
    _, prices = make_predictive_universe()
    for tags in classify_regimes(prices).values():
        assert "bull" in tags or "bear" in tags


def test_regime_test_passes_for_predictive_signal() -> None:
    scores, prices = make_predictive_universe()
    fr = compute_forward_returns(prices, DEFAULT_FORWARD_HORIZON_DAYS)
    result = regime_test(scores, fr, prices)
    assert result.n_positive >= 3
    assert result.passed is True
    assert set(result.by_regime).issubset(set(REGIMES))


def test_regime_test_fails_for_noise() -> None:
    _, prices = make_predictive_universe()
    noise = make_noise_scores(prices)
    fr = compute_forward_returns(prices, DEFAULT_FORWARD_HORIZON_DAYS)
    assert regime_test(noise, fr, prices).passed is False
