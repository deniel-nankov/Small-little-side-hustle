"""Data source package + the factory that selects an implementation from settings."""

from __future__ import annotations

from config.settings import DataSourceKind, Settings, get_settings

from src.data.source.base import DataSource
from src.data.source.fixture import FixtureSource

__all__ = ["DataSource", "FixtureSource", "get_data_source"]


def get_data_source(cfg: Settings | None = None) -> DataSource:
    """Return the configured :class:`DataSource` implementation.

    Args:
        cfg: Settings to read ``data_source`` from. Defaults to the process singleton.

    Returns:
        A ready-to-use data source instance.

    Raises:
        NotImplementedError: if ``data_source=factset`` — the real FactSet source lands
            in Milestone 2 (requires FactSet API entitlement). Use ``fixture`` until then.
    """
    cfg = cfg or get_settings()
    if cfg.data_source is DataSourceKind.fixture:
        return FixtureSource()
    if cfg.data_source is DataSourceKind.factset:
        raise NotImplementedError(
            "FactSetSource is implemented in Milestone 2 (needs FactSet API credentials). "
            "Set DATA_SOURCE=fixture to develop and test against synthetic data."
        )
    raise NotImplementedError(f"Unsupported data source: {cfg.data_source!r}")
