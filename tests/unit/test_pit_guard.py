"""Unit tests for the point-in-time leakage guard (Stage C, #31)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest
from src.data.contracts.schemas import (
    EstimateData,
    FundamentalData,
    Metric,
    OwnershipData,
    PriceData,
    Relationship,
    SupplyChainLink,
)
from src.data.source.base import DataSource
from src.data.source.fixture import FixtureSource
from src.monitoring.audit import AuditLog
from src.utils.pit import (
    PITDataSource,
    PointInTimeError,
    as_of,
    assert_point_in_time,
    knowledge_date,
)

from tests.synth import flat_bar

_CUTOFF = date(2026, 3, 31)
_BEFORE = date(2026, 3, 30)
_AFTER = date(2026, 4, 1)


# ---------------------------------------------------------------------------- knowledge_date


def test_knowledge_date_uses_report_date_for_fundamentals() -> None:
    record = FundamentalData(
        ticker="AAPL",
        report_date=_BEFORE,
        fiscal_year=2026,
        fiscal_quarter=1,
        total_assets=1.0,
        net_income=1.0,
        operating_cash_flow=1.0,
        revenue=1.0,
        is_point_in_time=True,
    )
    assert knowledge_date(record) == _BEFORE


def test_knowledge_date_uses_estimate_date_for_estimates() -> None:
    record = EstimateData(
        ticker="AAPL",
        analyst_id="AN001",
        broker="BRK01",
        estimate_date=_BEFORE,
        fiscal_year=2026,
        fiscal_quarter=1,
        metric=Metric.eps,
        value=1.5,
        currency="USD",
        is_point_in_time=True,
        analyst_accuracy=0.5,
    )
    assert knowledge_date(record) == _BEFORE


def test_knowledge_date_uses_as_of_date_for_ownership() -> None:
    record = OwnershipData(
        ticker="AAPL",
        as_of_date=_BEFORE,
        institutional_ownership_pct=0.5,
        institution_count=100,
        is_point_in_time=True,
    )
    assert knowledge_date(record) == _BEFORE


def test_knowledge_date_uses_date_for_prices() -> None:
    assert knowledge_date(flat_bar("AAPL", _BEFORE, 100.0)) == _BEFORE


def test_knowledge_date_rejects_dateless_records() -> None:
    link = SupplyChainLink(
        ticker="A",
        related_ticker="B",
        relationship=Relationship.supplier,
        weight=0.5,
        is_point_in_time=True,
    )
    with pytest.raises(TypeError, match="knowledge date"):
        knowledge_date(link)


# ---------------------------------------------------------------------------- as_of filter


def test_as_of_keeps_on_or_before_cutoff_only() -> None:
    bars = [flat_bar("A", d, 100.0) for d in (_BEFORE, _CUTOFF, _AFTER)]
    kept = as_of(bars, _CUTOFF)
    assert [b.date for b in kept] == [_BEFORE, _CUTOFF]


def test_as_of_empty_input() -> None:
    assert as_of([], _CUTOFF) == []


# ---------------------------------------------------------------------------- assert_point_in_time


def test_assert_passes_when_clean() -> None:
    bars = [flat_bar("A", _BEFORE, 100.0), flat_bar("A", _CUTOFF, 101.0)]
    assert_point_in_time(bars, _CUTOFF)  # must not raise


def test_assert_raises_with_offender_details() -> None:
    bars = [flat_bar("A", _CUTOFF, 100.0), flat_bar("A", _AFTER, 101.0)]
    with pytest.raises(PointInTimeError, match=r"1 record\(s\).*2026-04-01"):
        assert_point_in_time(bars, _CUTOFF, context="test-feed")


def test_assert_boundary_record_on_cutoff_passes() -> None:
    assert_point_in_time([flat_bar("A", _CUTOFF, 100.0)], _CUTOFF)


# ---------------------------------------------------------------------------- PITDataSource


class _LeakySource(DataSource):
    """A broken source that returns future-dated bars regardless of the asked range."""

    name = "leaky"

    def get_prices(self, tickers: Sequence[str], start: date, end: date) -> list[PriceData]:
        return [flat_bar(t, _AFTER, 100.0) for t in tickers]

    def get_estimates(self, tickers: Sequence[str], start: date, end: date) -> list[EstimateData]:
        raise NotImplementedError

    def get_fundamentals(
        self, tickers: Sequence[str], start: date, end: date
    ) -> list[FundamentalData]:
        raise NotImplementedError

    def get_ownership(self, tickers: Sequence[str], start: date, end: date) -> list[OwnershipData]:
        raise NotImplementedError

    def get_supply_chain(self, tickers: Sequence[str]) -> list[SupplyChainLink]:
        return []


def test_pit_source_clamps_end_to_as_of() -> None:
    pit = PITDataSource(FixtureSource(), as_of=_CUTOFF)
    bars = pit.get_prices(["AAPL"], date(2026, 3, 1), date(2026, 6, 30))
    assert bars  # data before the cutoff exists
    assert max(b.date for b in bars) <= _CUTOFF


def test_pit_source_filters_every_dated_endpoint() -> None:
    pit = PITDataSource(FixtureSource(), as_of=_CUTOFF)
    start, end = date(2026, 1, 1), date(2026, 12, 31)
    assert all(e.estimate_date <= _CUTOFF for e in pit.get_estimates(["AAPL"], start, end))
    assert all(f.report_date <= _CUTOFF for f in pit.get_fundamentals(["AAPL"], start, end))
    assert all(o.as_of_date <= _CUTOFF for o in pit.get_ownership(["AAPL"], start, end))


def test_pit_source_returns_empty_when_start_after_as_of() -> None:
    pit = PITDataSource(FixtureSource(), as_of=_CUTOFF)
    assert pit.get_prices(["AAPL"], _AFTER, date(2026, 6, 30)) == []


def test_pit_source_raises_on_leaky_underlying_source() -> None:
    pit = PITDataSource(_LeakySource(), as_of=_CUTOFF)
    with pytest.raises(PointInTimeError, match="leaky"):
        pit.get_prices(["AAPL"], date(2026, 3, 1), _CUTOFF)


def test_pit_source_passes_through_supply_chain_and_name() -> None:
    pit = PITDataSource(FixtureSource(), as_of=_CUTOFF)
    assert pit.name == "pit(fixture)"
    assert pit.get_supply_chain(["A", "B", "C"])  # undated edges pass through


def test_pit_source_records_clamp_to_audit_log(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    pit = PITDataSource(FixtureSource(), as_of=_CUTOFF, audit=audit)
    pit.get_prices(["AAPL"], date(2026, 3, 1), date(2026, 6, 30))  # end beyond as_of -> clamp

    entries = audit.entries()
    assert [e["event"] for e in entries] == ["pit.clamped"]
    assert entries[0]["payload"]["requested_end"] == "2026-06-30"
    assert entries[0]["payload"]["as_of"] == "2026-03-31"
    assert audit.verify() is True


def test_pit_source_no_audit_event_when_no_clamp_needed(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    pit = PITDataSource(FixtureSource(), as_of=_CUTOFF, audit=audit)
    pit.get_prices(["AAPL"], date(2026, 3, 1), _BEFORE)  # already inside the window
    assert audit.entries() == []
