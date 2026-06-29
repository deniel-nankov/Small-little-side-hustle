"""Deterministic synthetic :class:`DataSource` for tests and credential-free development.

Given the same inputs, ``FixtureSource`` always returns byte-identical data (seeded per
ticker/date), so tests are reproducible and require no network. All records are marked
``point_in_time=True`` and use ``data_source="fixture"`` so they can never be mistaken
for licensed production data.
"""

from __future__ import annotations

import random
from collections.abc import Iterator, Sequence
from datetime import date, timedelta

from src.data.contracts.schemas import (
    DataSourceName,
    EstimateData,
    FundamentalData,
    Metric,
    OwnershipData,
    PriceData,
    Relationship,
    SupplyChainLink,
)
from src.data.source.base import DataSource
from src.monitoring.logger import get_logger

_log = get_logger(__name__)


def _seeded_rng(*parts: object) -> random.Random:
    """Return a Random seeded deterministically from ``parts``."""
    return random.Random("|".join(str(p) for p in parts))


def _business_days(start: date, end: date) -> Iterator[date]:
    """Yield Mon–Fri dates in ``[start, end]`` inclusive."""
    if end < start:
        raise ValueError(f"end ({end}) precedes start ({start})")
    day = start
    while day <= end:
        if day.weekday() < 5:  # 0=Mon … 4=Fri
            yield day
        day += timedelta(days=1)


class FixtureSource(DataSource):
    """Synthetic data source producing valid, deterministic contracts."""

    name = DataSourceName.fixture.value

    def __init__(self, base_price: float = 100.0) -> None:
        """Initialize the source.

        Args:
            base_price: Notional starting price level for the synthetic random walk.
        """
        self._base_price = base_price

    def get_prices(self, tickers: Sequence[str], start: date, end: date) -> list[PriceData]:
        """See :meth:`DataSource.get_prices`."""
        out: list[PriceData] = []
        for ticker in tickers:
            price = self._base_price * (1 + _seeded_rng("price", ticker).uniform(-0.3, 0.3))
            for day in _business_days(start, end):
                rng = _seeded_rng("price", ticker, day.isoformat())
                price = max(1.0, price * (1 + rng.gauss(0.0, 0.02)))
                open_ = round(price * (1 + rng.uniform(-0.01, 0.01)), 4)
                close = round(price, 4)
                high = round(max(open_, close) * (1 + abs(rng.uniform(0.0, 0.01))), 4)
                low = round(min(open_, close) * (1 - abs(rng.uniform(0.0, 0.01))), 4)
                # Re-assert invariants after rounding (fail-safe, not just fail-fast).
                high = max(high, open_, close)
                low = min(low, open_, close)
                out.append(
                    PriceData(
                        ticker=ticker,
                        date=day,
                        open=open_,
                        high=high,
                        low=low,
                        close=close,
                        volume=float(rng.randint(100_000, 5_000_000)),
                        adjusted_close=close,
                        data_source=DataSourceName.fixture,
                        point_in_time=True,
                    )
                )
        _log.debug("fixture.get_prices", tickers=len(tickers), records=len(out))
        return out

    def get_estimates(self, tickers: Sequence[str], start: date, end: date) -> list[EstimateData]:
        """See :meth:`DataSource.get_estimates`."""
        if end < start:
            raise ValueError(f"end ({end}) precedes start ({start})")
        out: list[EstimateData] = []
        for ticker in tickers:
            rng = _seeded_rng("est", ticker)
            n_analysts = rng.randint(3, 6)
            for analyst in range(n_analysts):
                for metric in (Metric.eps, Metric.revenue):
                    base = 1.5 if metric is Metric.eps else 5_000.0
                    out.append(
                        EstimateData(
                            ticker=ticker,
                            analyst_id=f"AN{analyst:03d}",
                            broker=f"BRK{rng.randint(1, 20):02d}",
                            estimate_date=start,
                            fiscal_year=start.year,
                            fiscal_quarter=((start.month - 1) // 3) + 1,
                            metric=metric,
                            value=round(base * (1 + rng.gauss(0.0, 0.1)), 4),
                            currency="USD",
                            is_point_in_time=True,
                            analyst_accuracy=round(rng.uniform(0.4, 0.7), 3),
                        )
                    )
        _log.debug("fixture.get_estimates", tickers=len(tickers), records=len(out))
        return out

    def get_fundamentals(
        self, tickers: Sequence[str], start: date, end: date
    ) -> list[FundamentalData]:
        """See :meth:`DataSource.get_fundamentals`. Quarterly periods every ~91 days."""
        if end < start:
            raise ValueError(f"end ({end}) precedes start ({start})")
        out: list[FundamentalData] = []
        for ticker in tickers:
            assets = _seeded_rng("fund", ticker).uniform(1_000.0, 100_000.0)
            revenue = _seeded_rng("fund-rev", ticker).uniform(100.0, 10_000.0)
            day = start
            while day <= end:
                rng = _seeded_rng("fund", ticker, day.isoformat())
                revenue = max(1.0, revenue * (1 + rng.uniform(-0.05, 0.10)))
                net_income = revenue * rng.uniform(-0.05, 0.20)
                operating_cash_flow = net_income + revenue * rng.uniform(-0.05, 0.10)
                out.append(
                    FundamentalData(
                        ticker=ticker,
                        report_date=day,
                        fiscal_year=day.year,
                        fiscal_quarter=((day.month - 1) // 3) + 1,
                        total_assets=round(assets, 2),
                        net_income=round(net_income, 2),
                        operating_cash_flow=round(operating_cash_flow, 2),
                        revenue=round(revenue, 2),
                        is_point_in_time=True,
                    )
                )
                day += timedelta(days=91)
        _log.debug("fixture.get_fundamentals", tickers=len(tickers), records=len(out))
        return out

    def get_ownership(self, tickers: Sequence[str], start: date, end: date) -> list[OwnershipData]:
        """See :meth:`DataSource.get_ownership`. Monthly snapshots every ~30 days."""
        if end < start:
            raise ValueError(f"end ({end}) precedes start ({start})")
        out: list[OwnershipData] = []
        for ticker in tickers:
            pct = _seeded_rng("own", ticker).uniform(0.30, 0.80)
            day = start
            while day <= end:
                rng = _seeded_rng("own", ticker, day.isoformat())
                pct = min(0.99, max(0.01, pct + rng.uniform(-0.03, 0.03)))
                out.append(
                    OwnershipData(
                        ticker=ticker,
                        as_of_date=day,
                        institutional_ownership_pct=round(pct, 4),
                        institution_count=rng.randint(50, 500),
                        is_point_in_time=True,
                    )
                )
                day += timedelta(days=30)
        _log.debug("fixture.get_ownership", tickers=len(tickers), records=len(out))
        return out

    def get_supply_chain(self, tickers: Sequence[str]) -> list[SupplyChainLink]:
        """See :meth:`DataSource.get_supply_chain`. A deterministic ring of relationships."""
        names = list(tickers)
        n = len(names)
        out: list[SupplyChainLink] = []
        if n < 2:
            return out
        for i, ticker in enumerate(names):
            rng = _seeded_rng("sc", ticker)
            n_links = min(n - 1, rng.randint(1, 3))
            for j in range(1, n_links + 1):
                related = names[(i + j) % n]
                out.append(
                    SupplyChainLink(
                        ticker=ticker,
                        related_ticker=related,
                        relationship=(
                            Relationship.supplier if (i + j) % 2 == 0 else Relationship.customer
                        ),
                        weight=round(rng.uniform(0.10, 0.90), 3),
                        is_point_in_time=True,
                    )
                )
        _log.debug("fixture.get_supply_chain", tickers=n, links=len(out))
        return out
