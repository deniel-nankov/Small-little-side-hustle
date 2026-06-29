"""Unit tests for the signal-decay test."""

from __future__ import annotations

from datetime import date

import pytest
from src.data.contracts.schemas import SignalScore
from src.signals.validation.decay_tester import DECAY_HORIZON_DAYS, decay_test

from tests.synth import business_days, flat_bar, make_noise_scores, make_predictive_universe


def test_decay_passes_for_persistent_signal() -> None:
    scores, prices = make_predictive_universe()
    result = decay_test(scores, prices)
    assert result.horizon_days == DECAY_HORIZON_DAYS
    assert result.passed is True
    assert result.mean_ic > 0.01


def test_decay_fails_for_noise() -> None:
    _, prices = make_predictive_universe()
    noise = make_noise_scores(prices)
    assert decay_test(noise, prices).passed is False


def test_decay_respects_custom_horizon() -> None:
    scores, prices = make_predictive_universe()
    result = decay_test(scores, prices, horizon_days=10)
    assert result.horizon_days == 10
    assert result.passed is True


def test_decay_raises_when_series_shorter_than_horizon() -> None:
    days = business_days(date(2026, 1, 1), 10)
    prices = [flat_bar(f"T{i:02d}", d, 100.0 + i) for d in days for i in range(6)]
    scores = [
        SignalScore(
            ticker=f"T{i:02d}",
            date=d,
            signal_name="x",
            signal_version="1.0.0",
            raw_score=float(i),
            rank_score=0.5,
            data_inputs=["x"],
        )
        for d in days
        for i in range(6)
    ]
    with pytest.raises(ValueError, match="decay horizon"):
        decay_test(scores, prices, horizon_days=63)
