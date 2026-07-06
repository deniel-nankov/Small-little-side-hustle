"""Point-in-time leakage guard (Stage C, #31).

Enforces the team's hardest non-negotiable: **no data dated after the as-of date may
reach a signal**. Three layers of defense, composable and reusable:

* :func:`knowledge_date` — the single definition of "when did we know this record?"
  across every data contract (``report_date`` > ``estimate_date`` > ``as_of_date`` >
  ``date``, in that priority order).
* :func:`as_of` / :func:`assert_point_in_time` — filter or hard-fail any record set
  against a cutoff date.
* :class:`PITDataSource` — wraps any :class:`~src.data.source.base.DataSource` and pins
  it to an as-of date: requests are clamped, responses are re-verified, and a source
  that leaks future data raises :class:`PointInTimeError` instead of poisoning a signal.

A static counterpart lives in ``src.utils.compliance.check_no_wallclock_in_analytics``:
analytics code must be driven by explicit as-of dates, never the wall clock.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any, TypeVar

from src.data.source.base import DataSource
from src.monitoring.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from src.data.contracts.schemas import (
        EstimateData,
        FundamentalData,
        OwnershipData,
        PriceData,
        SupplyChainLink,
    )
    from src.monitoring.audit import AuditLog

_log = get_logger(__name__)

T = TypeVar("T")

#: Attribute checked first wins — ``report_date`` (fundamentals) before generic ``date``.
_KNOWLEDGE_DATE_ATTRS = ("report_date", "estimate_date", "as_of_date", "date")


class PointInTimeError(Exception):
    """Raised when data dated after the as-of date would be used."""


def knowledge_date(record: Any) -> date:
    """Return the date on which ``record`` became knowable (its point-in-time date).

    Args:
        record: Any data contract carrying one of the known date attributes.

    Returns:
        The record's knowledge date.

    Raises:
        TypeError: if the record carries no recognized date attribute.
    """
    for attr in _KNOWLEDGE_DATE_ATTRS:
        value = getattr(record, attr, None)
        if isinstance(value, date):
            return value
    raise TypeError(f"{type(record).__name__} has no knowledge date attribute")


def as_of(records: Iterable[T], cutoff: date) -> list[T]:
    """Return only the records knowable on or before ``cutoff``.

    Args:
        records: Dated records (see :func:`knowledge_date`).
        cutoff: The as-of date (inclusive).

    Returns:
        The records whose knowledge date is ``<= cutoff``, order preserved.
    """
    return [r for r in records if knowledge_date(r) <= cutoff]


def assert_point_in_time(records: Iterable[Any], cutoff: date, *, context: str = "") -> None:
    """Hard-fail if any record is dated after ``cutoff``.

    Args:
        records: Dated records to verify.
        cutoff: The as-of date (inclusive).
        context: Optional label (e.g. the data source name) included in the error.

    Raises:
        PointInTimeError: if one or more records post-date the cutoff.
    """
    offenders = [knowledge_date(r) for r in records if knowledge_date(r) > cutoff]
    if offenders:
        label = f" from {context}" if context else ""
        raise PointInTimeError(
            f"look-ahead leakage{label}: {len(offenders)} record(s) dated after "
            f"as-of {cutoff.isoformat()} (earliest offender: {min(offenders).isoformat()})"
        )


class PITDataSource(DataSource):
    """A :class:`DataSource` wrapper pinned to an as-of date.

    Every dated query is clamped to ``end <= as_of`` and the response is re-verified,
    so downstream signal code physically cannot observe the future — even against a
    buggy underlying source.

    Args:
        source: The underlying data source to wrap.
        as_of: The as-of date; no record knowable after this date is ever returned.
        audit: Optional tamper-evident audit log; clamped queries are recorded.
    """

    def __init__(self, source: DataSource, as_of: date, audit: AuditLog | None = None) -> None:
        """See class docstring for argument semantics."""
        self._source = source
        self._as_of = as_of
        self._audit = audit
        self.name = f"pit({source.name})"

    def _clamp(self, method: str, end: date) -> date:
        """Clamp ``end`` to the as-of date, logging and auditing when it bites."""
        if end <= self._as_of:
            return end
        _log.info("pit.clamped", method=method, requested_end=str(end), as_of=str(self._as_of))
        if self._audit is not None:
            self._audit.record(
                "pit.clamped",
                {
                    "method": method,
                    "requested_end": end.isoformat(),
                    "as_of": self._as_of.isoformat(),
                },
            )
        return self._as_of

    def _guarded(self, method: str, records: list[T]) -> list[T]:
        """Verify the underlying source honored the clamp; raise on leakage."""
        assert_point_in_time(records, self._as_of, context=f"{self._source.name}.{method}")
        return records

    def get_prices(self, tickers: Sequence[str], start: date, end: date) -> list[PriceData]:
        """See :meth:`DataSource.get_prices`, clamped to the as-of date."""
        if start > self._as_of:
            return []
        clamped = self._clamp("get_prices", end)
        return self._guarded("get_prices", self._source.get_prices(tickers, start, clamped))

    def get_estimates(self, tickers: Sequence[str], start: date, end: date) -> list[EstimateData]:
        """See :meth:`DataSource.get_estimates`, clamped to the as-of date."""
        if start > self._as_of:
            return []
        clamped = self._clamp("get_estimates", end)
        return self._guarded(
            "get_estimates", self._source.get_estimates(tickers, start, clamped)
        )

    def get_fundamentals(
        self, tickers: Sequence[str], start: date, end: date
    ) -> list[FundamentalData]:
        """See :meth:`DataSource.get_fundamentals`, clamped to the as-of date."""
        if start > self._as_of:
            return []
        clamped = self._clamp("get_fundamentals", end)
        return self._guarded(
            "get_fundamentals", self._source.get_fundamentals(tickers, start, clamped)
        )

    def get_ownership(self, tickers: Sequence[str], start: date, end: date) -> list[OwnershipData]:
        """See :meth:`DataSource.get_ownership`, clamped to the as-of date."""
        if start > self._as_of:
            return []
        clamped = self._clamp("get_ownership", end)
        return self._guarded(
            "get_ownership", self._source.get_ownership(tickers, start, clamped)
        )

    def get_supply_chain(self, tickers: Sequence[str]) -> list[SupplyChainLink]:
        """See :meth:`DataSource.get_supply_chain` (undated edges pass through)."""
        return self._source.get_supply_chain(tickers)
