"""Integration test: data source -> signal -> score, on synthetic data.

Placeholder — fleshed out as signal modules land (Milestone 3+). Uses the fixture
source so it can run with no credentials.
"""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skip(reason="Milestone 3: pipeline not yet wired"),
]


def test_signal_pipeline_end_to_end_on_fixtures() -> None:
    raise NotImplementedError
