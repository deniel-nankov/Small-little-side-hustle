"""PublicSource — free real data (Yahoo prices + EDGAR fundamentals) as a DataSource.

Select with ``DATA_SOURCE=public``. Needs no credentials; EDGAR asks only for an
identifying ``User-Agent`` (``EDGAR_USER_AGENT`` in ``.env``). Endpoints with no free
equivalent (estimates, ownership, supply chain) raise ``NotImplementedError`` until the
FactSet entitlement lands or a free parser (e.g. EDGAR 13F) is built.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.data.public.edgar import EdgarClient
from src.data.public.yahoo import YahooPriceClient
from src.data.source.base import DataSource

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from config.settings import Settings

    from src.data.contracts.schemas import (
        EstimateData,
        FundamentalData,
        OwnershipData,
        PriceData,
        SupplyChainLink,
    )
    from src.data.public.client import Transport


class PublicSource(DataSource):
    """Free public data (Yahoo + EDGAR) behind the standard DataSource interface."""

    name = "public"

    def __init__(self, prices: YahooPriceClient, fundamentals: EdgarClient) -> None:
        """Compose the source from its two clients (injectable for tests)."""
        self._prices = prices
        self._fundamentals = fundamentals

    @classmethod
    def from_settings(cls, cfg: Settings, *, transport: Transport | None = None) -> PublicSource:
        """Build a PublicSource from settings.

        Args:
            cfg: Runtime settings (``edgar_user_agent`` is read).
            transport: Optional injected transport shared by both clients (for tests).

        Returns:
            A ready-to-use source.
        """
        return cls(
            prices=YahooPriceClient(transport=transport),
            fundamentals=EdgarClient(cfg.edgar_user_agent, transport=transport),
        )

    def get_prices(self, tickers: Sequence[str], start: date, end: date) -> list[PriceData]:
        """See :meth:`DataSource.get_prices` (served by Yahoo Finance)."""
        return self._prices.get_prices(tickers, start, end)

    def get_fundamentals(
        self, tickers: Sequence[str], start: date, end: date
    ) -> list[FundamentalData]:
        """See :meth:`DataSource.get_fundamentals` (served by EDGAR, point-in-time)."""
        return self._fundamentals.get_fundamentals(tickers, start, end)

    def get_estimates(self, tickers: Sequence[str], start: date, end: date) -> list[EstimateData]:
        """No free source for analyst estimates — needs FactSet entitlement."""
        raise NotImplementedError("estimates need FactSet entitlement (no free equivalent)")

    def get_ownership(self, tickers: Sequence[str], start: date, end: date) -> list[OwnershipData]:
        """Not built yet — EDGAR 13F parsing is a planned follow-up ticket."""
        raise NotImplementedError("ownership via EDGAR 13F parser is a planned follow-up")

    def get_supply_chain(self, tickers: Sequence[str]) -> list[SupplyChainLink]:
        """No free source for supply-chain links — needs FactSet Revere."""
        raise NotImplementedError("supply chain needs FactSet Revere (no free equivalent)")
