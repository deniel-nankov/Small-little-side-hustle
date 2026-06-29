"""Integration test: the full validation chain on a realistic-size synthetic universe."""

from __future__ import annotations

import pytest
from src.data.contracts.schemas import BacktestResult
from src.signals.validation.backtest_runner import run_backtest

from tests.synth import make_predictive_universe

pytestmark = pytest.mark.integration


def test_full_validation_chain_on_predictive_universe() -> None:
    scores, prices = make_predictive_universe()
    result = run_backtest(scores, prices, n_trials=1)
    assert isinstance(result, BacktestResult)
    assert result.passed_validation is True
    assert result.icir > 0.5
    assert result.regime_results
