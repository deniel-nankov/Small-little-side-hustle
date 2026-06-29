"""Unit tests for the tamper-evident audit log (ticket: audit-log & no-leakage, Stage H)."""

from __future__ import annotations

from pathlib import Path

from src.monitoring.audit import AuditLog


def test_record_returns_hash_and_stores_entry(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl")
    digest = log.record("signal.validated", {"name": "truebeats", "ic": 0.03})
    assert len(digest) == 64
    entries = log.entries()
    assert len(entries) == 1
    assert entries[0]["event"] == "signal.validated"
    assert entries[0]["payload"]["name"] == "truebeats"
    assert entries[0]["hash"] == digest
    assert entries[0]["prev_hash"] is None


def test_entries_are_hash_chained(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "a.jsonl")
    first = log.record("a", {})
    second = log.record("b", {})
    entries = log.entries()
    assert entries[1]["prev_hash"] == first
    assert entries[1]["hash"] == second


def test_verify_true_for_untampered_log(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "a.jsonl")
    log.record("a", {"x": 1})
    log.record("b", {"y": 2})
    assert log.verify() is True


def test_verify_false_after_tampering(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    log = AuditLog(path)
    log.record("a", {"x": 1})
    log.record("b", {"y": 2})
    tampered = path.read_text().replace('"x": 1', '"x": 999')
    path.write_text(tampered)
    assert log.verify() is False


def test_persists_and_chains_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    AuditLog(path).record("a", {"x": 1})
    log2 = AuditLog(path)
    log2.record("b", {"y": 2})
    entries = log2.entries()
    assert entries[1]["prev_hash"] == entries[0]["hash"]
    assert log2.verify() is True
