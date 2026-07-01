"""FactSet-backed :class:`DataSource` implementation (Stage 2).

Currently implements ``get_prices`` against the FactSet Global Prices API; the other methods
raise ``NotImplementedError`` until their specs/entitlements land (blocker protocol). Maps
the API response to our ``PriceData`` contract so it is a drop-in for ``FixtureSource``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from config.settings import Settings, get_settings
from pydantic import ValidationError

from src.data.contracts.schemas import (
    DataSourceName,
    EstimateData,
    FundamentalData,
    OwnershipData,
    PriceData,
    SupplyChainLink,
)
from src.data.factset.client import FactSetClient
from src.data.source.base import DataSource
from src.monitoring.logger import get_logger

_log = get_logger(__name__)

PRICES_PATH = "/factset-global-prices/v1/prices"

#: Split-only adjusted OHLC (known, point-in-time-safe corporate-action factors).
_ADJUST_OHLC = "SPLIT"
#: Fully adjusted close (splits+spinoffs+dividends) for total-return calculations.
_ADJUST_TOTAL_RETURN = "DIV_SPIN_SPLITS"
_OHLC_FIELDS = ["price", "priceOpen", "priceHigh", "priceLow", "volume"]


class FactSetSource(DataSource):
    """DataSource backed by the FactSet content APIs."""

    name = DataSourceName.factset.value

    def __init__(
        self, client: FactSetClient, *, default_region: str = "US", currency: str = "USD"
    ) -> None:
        """Initialize the source.

        Args:
            client: Configured FactSet HTTP client.
            default_region: Region suffix appended to bare tickers (``AAPL`` -> ``AAPL-US``).
            currency: Currency for price adjustment.
        """
        self._client = client
        self._region = default_region
        self._currency = currency

    @classmethod
    def from_settings(cls, cfg: Settings | None = None) -> FactSetSource:
        """Build a source from configuration, requiring FactSet credentials.

        Raises:
            MissingCredentialError: if FactSet credentials are not set.
        """
        cfg = cfg or get_settings()
        cfg.require("factset_client_id", "factset_client_secret")
        if cfg.factset_client_id is None or cfg.factset_client_secret is None:  # pragma: no cover
            raise AssertionError("require() should have guaranteed FactSet credentials")
        client = FactSetClient(
            cfg.factset_client_id.get_secret_value(),
            cfg.factset_client_secret.get_secret_value(),
        )
        return cls(client)

    def _to_factset_id(self, ticker: str) -> str:
        return ticker if "-" in ticker else f"{ticker}-{self._region}"

    @staticmethod
    def _to_ticker(request_id: str) -> str:
        return request_id.split("-", 1)[0] if request_id else request_id

    def get_prices(self, tickers: Sequence[str], start: date, end: date) -> list[PriceData]:
        """See :meth:`DataSource.get_prices`.

        Two calls: split-adjusted OHLC (``adjust=SPLIT``) and the fully-adjusted close
        (``adjust=DIV_SPIN_SPLITS``) for ``adjusted_close``. Rows that fail contract
        validation are skipped with a warning rather than failing the whole pull.
        """
        if end < start:
            raise ValueError(f"end ({end}) precedes start ({start})")
        ids = [self._to_factset_id(t) for t in tickers]
        common: dict[str, Any] = {
            "ids": ids,
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "frequency": "D",
            "calendar": "FIVEDAY",
            "currency": self._currency,
        }
        ohlc = self._client.get_json(
            PRICES_PATH, {**common, "adjust": _ADJUST_OHLC, "fields": _OHLC_FIELDS}
        )
        adjusted = self._client.get_json(
            PRICES_PATH, {**common, "adjust": _ADJUST_TOTAL_RETURN, "fields": ["price"]}
        )
        adjusted_by_key = {
            (row.get("requestId"), row.get("date")): row.get("price")
            for row in adjusted.get("data", [])
            if row.get("price") is not None
        }

        out: list[PriceData] = []
        skipped = 0
        for row in ohlc.get("data", []):
            close = row.get("price")
            date_str = row.get("date")
            request_id = row.get("requestId")
            if close is None or date_str is None or request_id is None:
                skipped += 1
                continue
            adjusted_close = adjusted_by_key.get((request_id, date_str), close)
            try:
                out.append(
                    PriceData(
                        ticker=self._to_ticker(request_id),
                        date=date.fromisoformat(date_str),
                        open=row.get("priceOpen") or close,
                        high=row.get("priceHigh") or close,
                        low=row.get("priceLow") or close,
                        close=close,
                        volume=row.get("volume") or 0.0,
                        adjusted_close=adjusted_close,
                        data_source=DataSourceName.factset,
                        point_in_time=True,
                    )
                )
            except ValidationError as exc:
                skipped += 1
                _log.warning(
                    "factset.price.invalid", request_id=request_id, date=date_str, error=str(exc)
                )
        _log.info("factset.get_prices", tickers=len(tickers), records=len(out), skipped=skipped)
        return out

    # --- deferred until their specs/entitlements land (blocker protocol) ---
    def get_estimates(self, tickers: Sequence[str], start: date, end: date) -> list[EstimateData]:
        """Not yet implemented — FactSet Estimates API spec/entitlement pending."""
        raise NotImplementedError("FactSet estimates pending (Estimates API spec + entitlement)")

    def get_fundamentals(
        self, tickers: Sequence[str], start: date, end: date
    ) -> list[FundamentalData]:
        """Not yet implemented — FactSet Fundamentals API spec/entitlement pending."""
        raise NotImplementedError("FactSet fundamentals pending (Fundamentals API)")

    def get_ownership(self, tickers: Sequence[str], start: date, end: date) -> list[OwnershipData]:
        """Not yet implemented — FactSet Ownership API spec/entitlement pending."""
        raise NotImplementedError("FactSet ownership pending (Ownership API)")

    def get_supply_chain(self, tickers: Sequence[str]) -> list[SupplyChainLink]:
        """Not yet implemented — FactSet Supply Chain API spec/entitlement pending."""
        raise NotImplementedError("FactSet supply chain pending (Supply Chain Relationships API)")
