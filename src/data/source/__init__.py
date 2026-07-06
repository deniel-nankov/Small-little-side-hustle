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
        MissingCredentialError: if ``data_source=factset`` but FactSet credentials are unset.
    """
    cfg = cfg or get_settings()
    if cfg.data_source is DataSourceKind.fixture:
        return FixtureSource()
    if cfg.data_source is DataSourceKind.factset:
        from src.data.factset.source import FactSetSource  # local import (needs credentials)

        return FactSetSource.from_settings(cfg)
    if cfg.data_source is DataSourceKind.public:
        from src.data.public.source import PublicSource  # local import (network-backed)

        return PublicSource.from_settings(cfg)
    raise NotImplementedError(f"Unsupported data source: {cfg.data_source!r}")
