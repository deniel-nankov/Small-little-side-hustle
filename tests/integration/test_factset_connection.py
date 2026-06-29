"""Integration test: real FactSet API connection (small request).

Placeholder — lands in Milestone 2. Requires FactSet API credentials and is skipped
automatically when they are absent, so CI stays green without secrets.
"""

import pytest
from config.settings import get_settings

pytestmark = pytest.mark.integration


def test_factset_connection_returns_valid_schema() -> None:
    cfg = get_settings()
    if not cfg.factset_client_id:
        pytest.skip("FactSet credentials not configured")
    raise NotImplementedError("Milestone 2: FactSet client not yet implemented")
