"""Unit tests for the signal registry (ticket: Signal registry, Stage 3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from src.data.contracts.schemas import SignalStatus
from src.monitoring.audit import AuditLog
from src.signals.registry.signal_registry import (
    DuplicateSignalError,
    SignalNotFoundError,
    SignalRecord,
    SignalRegistry,
    TransitionError,
)


def _rec(name: str = "truebeats", status: SignalStatus = SignalStatus.discovered) -> SignalRecord:
    return SignalRecord(
        name=name,
        version="1.0.0",
        status=status,
        description="DIY earnings-surprise signal",
        data_sources=["estimates"],
    )


def test_register_and_get_roundtrip() -> None:
    reg = SignalRegistry()
    reg.register(_rec())
    got = reg.get("truebeats")
    assert got is not None
    assert got.name == "truebeats"
    assert got.status is SignalStatus.discovered
    assert got.data_sources == ["estimates"]


def test_register_duplicate_raises() -> None:
    reg = SignalRegistry()
    reg.register(_rec())
    with pytest.raises(DuplicateSignalError):
        reg.register(_rec())


def test_get_absent_is_none_and_require_raises() -> None:
    reg = SignalRegistry()
    assert reg.get("nope") is None
    with pytest.raises(SignalNotFoundError):
        reg.require("nope")


def test_list_signals_filters_by_status() -> None:
    reg = SignalRegistry()
    reg.register(_rec("a", SignalStatus.discovered))
    reg.register(_rec("b", SignalStatus.validated))
    assert [r.name for r in reg.list_signals()] == ["a", "b"]
    assert [r.name for r in reg.list_signals(SignalStatus.validated)] == ["b"]


def test_valid_transition_stamps_timestamp() -> None:
    reg = SignalRegistry()
    reg.register(_rec())
    updated = reg.update_status("truebeats", SignalStatus.validated)
    assert updated.status is SignalStatus.validated
    assert updated.validated_at is not None
    stored = reg.get("truebeats")
    assert stored is not None
    assert stored.validated_at is not None


def test_invalid_transition_raises() -> None:
    reg = SignalRegistry()
    reg.register(_rec())
    with pytest.raises(TransitionError, match="cannot move"):
        reg.update_status("truebeats", SignalStatus.production)


def test_any_status_can_retire_and_retired_is_terminal() -> None:
    reg = SignalRegistry()
    reg.register(_rec(status=SignalStatus.staging))
    retired = reg.update_status("truebeats", SignalStatus.retired)
    assert retired.status is SignalStatus.retired
    assert retired.retired_at is not None
    with pytest.raises(TransitionError):
        reg.update_status("truebeats", SignalStatus.production)


def test_update_metrics_only_changes_provided_fields() -> None:
    reg = SignalRegistry()
    reg.register(_rec())
    reg.update_metrics("truebeats", mean_ic=0.03)
    reg.update_metrics("truebeats", sharpe=1.4)
    stored = reg.require("truebeats")
    assert stored.mean_ic == 0.03
    assert stored.sharpe == 1.4
    assert stored.icir is None


def test_persists_across_reopen(tmp_path: Path) -> None:
    db = str(tmp_path / "registry.db")
    with SignalRegistry(db) as reg:
        reg.register(_rec())
        reg.update_status("truebeats", SignalStatus.validated)
    with SignalRegistry(db) as reopened:
        stored = reopened.get("truebeats")
        assert stored is not None
        assert stored.status is SignalStatus.validated
        assert stored.validated_at is not None


def test_registry_writes_to_audit_log(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    reg = SignalRegistry(audit=audit)
    reg.register(_rec())
    reg.update_status("truebeats", SignalStatus.validated)

    events = [entry["event"] for entry in audit.entries()]
    assert "signal.registered" in events
    assert "signal.transition" in events
    assert audit.verify() is True  # tamper-evident trail intact

    transition = next(e for e in audit.entries() if e["event"] == "signal.transition")
    assert transition["payload"]["from"] == "DISCOVERED"
    assert transition["payload"]["to"] == "VALIDATED"


def test_registry_without_audit_is_unaffected() -> None:
    reg = SignalRegistry()  # no audit log attached
    reg.register(_rec())
    reg.update_status("truebeats", SignalStatus.validated)
    assert reg.require("truebeats").status is SignalStatus.validated
