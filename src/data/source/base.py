"""The :class:`DataSource` abstraction.

ALL data ingestion goes through this interface so the rest of the platform is
independent of FactSet entitlement status. Two implementations exist:

* :class:`~src.data.source.fixture.FixtureSource` — deterministic synthetic data, needs
  no credentials, used everywhere in tests and local development.
* ``FactSetSource`` (Milestone 2) — the real FactSet-backed implementation.

Every method returns validated data contracts (``src.data.contracts.schemas``), never raw
dicts or DataFrames (PRINCIPLES.md Golden Rule).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date

from src.data.contracts.schemas import (
    EstimateData,
    FundamentalData,
    OwnershipData,
    PriceData,
    SupplyChainLink,
)


class DataSource(ABC):
    """Abstract source of point-in-time financial data."""

    #: Human-readable source name; also the value placed in ``PriceData.data_source``.
    name: str

    @abstractmethod
    def get_prices(self, tickers: Sequence[str], start: date, end: date) -> list[PriceData]:
        """Return daily OHLCV bars for ``tickers`` over ``[start, end]`` inclusive.

        Args:
            tickers: Ticker symbols to fetch.
            start: First date (inclusive).
            end: Last date (inclusive).

        Returns:
            A list of :class:`PriceData`, one per ticker per trading day.

        Raises:
            ValueError: if ``end`` precedes ``start``.
        """

    @abstractmethod
    def get_estimates(self, tickers: Sequence[str], start: date, end: date) -> list[EstimateData]:
        """Return individual analyst estimates issued within ``[start, end]``.

        Args:
            tickers: Ticker symbols to fetch.
            start: First estimate date (inclusive).
            end: Last estimate date (inclusive).

        Returns:
            A list of :class:`EstimateData`, one per analyst per metric per period.

        Raises:
            ValueError: if ``end`` precedes ``start``.
        """

    @abstractmethod
    def get_fundamentals(
        self, tickers: Sequence[str], start: date, end: date
    ) -> list[FundamentalData]:
        """Return point-in-time fundamentals reported within ``[start, end]``.

        Args:
            tickers: Ticker symbols to fetch.
            start: First report date (inclusive).
            end: Last report date (inclusive).

        Returns:
            A list of :class:`FundamentalData`, one per ticker per fiscal period.

        Raises:
            ValueError: if ``end`` precedes ``start``.
        """

    @abstractmethod
    def get_ownership(self, tickers: Sequence[str], start: date, end: date) -> list[OwnershipData]:
        """Return institutional-ownership snapshots within ``[start, end]``.

        Args:
            tickers: Ticker symbols to fetch.
            start: First snapshot date (inclusive).
            end: Last snapshot date (inclusive).

        Returns:
            A list of :class:`OwnershipData`, one per ticker per snapshot date.

        Raises:
            ValueError: if ``end`` precedes ``start``.
        """

    @abstractmethod
    def get_supply_chain(self, tickers: Sequence[str]) -> list[SupplyChainLink]:
        """Return supplier/customer relationships among ``tickers``.

        Args:
            tickers: Ticker symbols whose relationships to return.

        Returns:
            A list of :class:`SupplyChainLink` (directed edges within the universe).
        """
