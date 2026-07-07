"""Unit tests for the AlphaAgent-style decay-resistance filter (Stage 4, #53).

Pins the paper's regularizers (arXiv:2502.16789): AST originality vs the existing
library, complexity constraints (symbolic length SL + parameter count PC), and the
parsimony term log(1+|Ff|). A candidate that replicates a known factor, or is
over-engineered, must be rejected BEFORE any backtest money is spent on it.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from src.monitoring.audit import AuditLog
from src.signals.discovery.alpha_agent import (
    FilterThresholds,
    RegularizationWeights,
    decay_resistance_filter,
    feature_count,
    originality_penalty,
    regularization_penalty,
)
from src.signals.discovery.factor_dsl import Binary, Feature, TimeSeries, Unary

_MOMENTUM = TimeSeries("momentum", Feature("adjclose"), 21)
_VOL = TimeSeries("ts_std", Feature("ret"), 21)
_NOVEL = Binary("div", TimeSeries("delta", Feature("volume"), 5), _VOL)


# ---------------------------------------------------------------------- feature_count


def test_feature_count_counts_distinct_leaves() -> None:
    assert feature_count(_MOMENTUM) == 1
    assert feature_count(_NOVEL) == 2  # volume + ret
    assert feature_count(Binary("add", Feature("close"), Feature("close"))) == 1


# ----------------------------------------------------------------- originality S(f)


def test_originality_zero_against_empty_library() -> None:
    assert originality_penalty(_MOMENTUM, []) == 0.0


def test_originality_one_for_exact_replica() -> None:
    assert originality_penalty(_MOMENTUM, [_MOMENTUM]) == 1.0


def test_originality_partial_for_shared_subtree() -> None:
    # _NOVEL contains _VOL as a subtree (2 of its 5 nodes; windows are params, not nodes).
    s = originality_penalty(_NOVEL, [_VOL])
    assert 0.0 < s < 1.0
    assert s == pytest.approx(2 / 5)


def test_originality_takes_worst_case_over_library() -> None:
    worst = originality_penalty(_NOVEL, [_MOMENTUM, _VOL, _NOVEL])
    assert worst == 1.0  # its own replica is in the library


# ------------------------------------------------------- regularization penalty ER(f)


def test_penalty_combines_terms_per_paper() -> None:
    weights = RegularizationWeights(originality=2.0, parsimony=0.5)
    penalty = regularization_penalty(_NOVEL, [_VOL], weights=weights)
    expected = 2.0 * (2 / 5) + 0.5 * math.log(1 + 2)
    assert penalty == pytest.approx(expected)


def test_penalty_is_zero_for_bare_novel_feature() -> None:
    weights = RegularizationWeights(originality=1.0, parsimony=0.0)
    assert regularization_penalty(Feature("volume"), [], weights=weights) == 0.0


# ------------------------------------------------------------------------ the filter


def test_filter_accepts_clean_novel_factor() -> None:
    verdict = decay_resistance_filter(_NOVEL, library=[_MOMENTUM])
    assert verdict.accepted is True
    assert verdict.reasons == []
    assert verdict.symbolic_length == 5
    assert verdict.parameter_count == 2


def test_filter_rejects_replica_of_library_factor() -> None:
    verdict = decay_resistance_filter(_MOMENTUM, library=[_MOMENTUM])
    assert verdict.accepted is False
    assert any("originality" in r for r in verdict.reasons)


def test_filter_rejects_overcomplex_expression() -> None:
    expr = _NOVEL
    for _ in range(6):  # bloat the tree well past the SL bound
        expr = Binary("add", expr, Unary("abs", expr))
    verdict = decay_resistance_filter(expr, library=[])
    assert verdict.accepted is False
    assert any("symbolic length" in r for r in verdict.reasons)


def test_filter_rejects_too_many_parameters() -> None:
    expr = _NOVEL
    for window in (2, 3, 5, 10, 21):
        expr = TimeSeries("ts_mean", expr, window)
    verdict = decay_resistance_filter(expr, library=[], thresholds=FilterThresholds())
    assert verdict.accepted is False
    assert any("parameter" in r for r in verdict.reasons)


def test_filter_collects_multiple_reasons() -> None:
    expr = _MOMENTUM
    for window in (2, 3, 5, 10, 21, 63):
        expr = TimeSeries("ts_max", expr, window)
    verdict = decay_resistance_filter(expr, library=[expr])
    assert verdict.accepted is False
    assert len(verdict.reasons) >= 2  # unoriginal AND over-parameterized


def test_filter_thresholds_are_tunable() -> None:
    tight = FilterThresholds(max_similarity=0.2)
    verdict = decay_resistance_filter(_NOVEL, library=[_VOL], thresholds=tight)
    assert verdict.accepted is False  # 2/5 similarity > 0.2


def test_filter_records_verdict_to_audit_log(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "audit.jsonl")
    decay_resistance_filter(_NOVEL, library=[_MOMENTUM], audit=audit)
    entries = audit.entries()
    assert [e["event"] for e in entries] == ["discovery.factor_filtered"]
    assert entries[0]["payload"]["accepted"] is True
    assert entries[0]["payload"]["expression"] == str(_NOVEL)
    assert audit.verify() is True
