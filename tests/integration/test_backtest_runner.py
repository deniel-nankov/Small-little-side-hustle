"""Integration test: backtest runner over a small synthetic window.

Placeholder — lands in Milestone 3 (src/signals/validation/backtest_runner.py).
"""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skip(reason="Milestone 3: backtest_runner not yet implemented"),
]


def test_backtest_runner_produces_backtest_result() -> None:
    raise NotImplementedError
