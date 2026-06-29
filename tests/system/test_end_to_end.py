"""System test: full pipeline from data pull to portfolio weights.

Placeholder — lands in Milestone 5/6. Run monthly and before any live session
(TESTING.md). Skipped until the pipeline exists.
"""

import pytest

pytestmark = [
    pytest.mark.system,
    pytest.mark.skip(reason="Milestone 5/6: end-to-end pipeline not yet built"),
]


def test_end_to_end_data_to_portfolio_weights() -> None:
    raise NotImplementedError
