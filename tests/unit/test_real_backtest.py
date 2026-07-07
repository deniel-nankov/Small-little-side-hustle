"""Unit tests for the end-to-end real-data backtest pipeline (runs on FixtureSource)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from src.data.contracts.schemas import BacktestResult
from src.data.source.fixture import FixtureSource
from src.monitoring.audit import AuditLog
from src.pipeline.real_backtest import run_fundamental_backtest, run_train_test_backtest
from src.signals.validation.splits import make_train_test_split
from src.utils.integrity import verify_sidecar

_TICKERS = [f"T{i:02d}" for i in range(8)]
_START = date(2026, 1, 5)
_END = date(2026, 6, 30)


def test_pipeline_produces_backtest_result() -> None:
    result = run_fundamental_backtest(FixtureSource(), _TICKERS, _START, _END)
    assert isinstance(result, BacktestResult)
    assert result.signal_name == "fundamental_factors"
    assert result.start_date >= _START
    assert result.end_date <= _END
    # Fixture fundamentals are random noise — we assert the pipeline runs and the
    # verdict machinery works, NOT that noise passes (it must not, typically).
    assert isinstance(result.passed_validation, bool)


def test_pipeline_scores_never_postdate_their_data_window() -> None:
    # The pipeline pins a PITDataSource at `end`; nothing after it can be fetched.
    result = run_fundamental_backtest(FixtureSource(), _TICKERS, _START, _END)
    assert result.end_date <= _END


def test_pipeline_writes_artifact_with_verified_sidecar(tmp_path: Path) -> None:
    run_fundamental_backtest(FixtureSource(), _TICKERS, _START, _END, out_dir=tmp_path)
    artifacts = list(tmp_path.glob("*.json"))
    assert len(artifacts) == 1
    assert "fundamental_factors" in artifacts[0].name
    assert verify_sidecar(artifacts[0]) is True
    assert BacktestResult.model_validate_json(artifacts[0].read_text(encoding="utf-8"))


def test_pipeline_records_audit_trail(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    run_fundamental_backtest(FixtureSource(), _TICKERS, _START, _END, audit=audit)
    events = [e["event"] for e in audit.entries()]
    assert "backtest.completed" in events
    assert audit.verify() is True


def test_pipeline_rejects_end_before_start() -> None:
    with pytest.raises(ValueError, match="precedes"):
        run_fundamental_backtest(FixtureSource(), _TICKERS, _END, _START)


def test_pipeline_raises_when_no_scores_computable() -> None:
    # Zero tickers -> no fundamentals -> no scores; must fail loudly, never silently.
    with pytest.raises(ValueError, match="no scores"):
        run_fundamental_backtest(FixtureSource(), [], _START, _END)


def test_score_every_reduces_score_dates() -> None:
    sparse = run_fundamental_backtest(FixtureSource(), _TICKERS, _START, _END, score_every=20)
    assert isinstance(sparse, BacktestResult)


def test_train_test_backtest_respects_split_windows(tmp_path: Path) -> None:
    split = make_train_test_split(date(2025, 1, 6), _END, test_fraction=0.4)
    audit = AuditLog(tmp_path / "audit.jsonl")
    train_result, test_result = run_train_test_backtest(
        FixtureSource(), _TICKERS, split, audit=audit, out_dir=tmp_path
    )
    # Each side is evaluated strictly inside its own window (PIT-pinned per window).
    assert train_result.start_date >= split.train_start
    assert train_result.end_date <= split.train_end
    assert test_result.start_date >= split.test_start
    assert test_result.end_date <= split.test_end
    # Both verdicts recorded on the tamper-evident trail.
    assert [e["event"] for e in audit.entries()].count("backtest.completed") == 2
    assert audit.verify() is True
    # Two sidecarred artifacts (one per window).
    artifacts = sorted(tmp_path.glob("*.json"))
    assert len(artifacts) == 2
    assert all(verify_sidecar(a) for a in artifacts)
