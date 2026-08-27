"""Unit tests for point-in-time analyst accuracy scoring (TrueBeats' expert component).

Accuracy is what makes TrueBeats more than a consensus average: it weights each analyst
by how well they have actually forecast this metric in the past. That makes it a prime
look-ahead hazard, so the rules pinned here are strict:

* an actual may only inform accuracy once it has been ANNOUNCED (``announced_date``);
* only estimates published BEFORE that announcement count as forecasts;
* an analyst with too little history gets no score (the caller supplies a prior).
"""

from __future__ import annotations

from datetime import date

import pytest
from src.data.contracts.schemas import ActualData, EstimateData, Metric
from src.signals.construction.analyst_accuracy import (
    MIN_OBSERVATIONS,
    analyst_accuracy,
    enrich_with_accuracy,
)


def _est(analyst: str, value: float, day: str, fy: int = 2026, fq: int = 1) -> EstimateData:
    return EstimateData(
        ticker="ORCL",
        analyst_id=analyst,
        broker="210",
        estimate_date=date.fromisoformat(day),
        fiscal_year=fy,
        fiscal_quarter=fq,
        metric=Metric.eps,
        value=value,
        currency="USD",
        is_point_in_time=True,
    )


def _act(value: float, announced: str, fy: int = 2026, fq: int = 1) -> ActualData:
    return ActualData(
        ticker="ORCL",
        fiscal_year=fy,
        fiscal_quarter=fq,
        metric=Metric.eps,
        value=value,
        announced_date=date.fromisoformat(announced),
        is_point_in_time=True,
    )


def _two_periods() -> tuple[list[EstimateData], list[ActualData]]:
    # "sharp" is nearly right both times; "sloppy" is far off both times.
    estimates = [
        _est("sharp", 1.02, "2026-01-10", fq=1),
        _est("sloppy", 1.50, "2026-01-10", fq=1),
        _est("sharp", 2.01, "2026-04-10", fq=2),
        _est("sloppy", 2.60, "2026-04-10", fq=2),
    ]
    actuals = [_act(1.00, "2026-02-01", fq=1), _act(2.00, "2026-05-01", fq=2)]
    return estimates, actuals


def test_more_accurate_analyst_scores_higher() -> None:
    estimates, actuals = _two_periods()
    scores = analyst_accuracy(estimates, actuals, as_of=date(2026, 6, 1), min_observations=2)
    assert scores["sharp"] > scores["sloppy"]
    assert all(0.0 <= v <= 1.0 for v in scores.values())  # contract bounds


def test_accuracy_ignores_actuals_not_yet_announced() -> None:
    estimates, actuals = _two_periods()
    # Before ANY result is public there is no track record to speak of.
    assert analyst_accuracy(estimates, actuals, as_of=date(2026, 1, 15)) == {}
    # After Q1 only, one observation exists — not yet enough under the default minimum.
    assert analyst_accuracy(estimates, actuals, as_of=date(2026, 3, 1)) == {}
    after_q1 = analyst_accuracy(estimates, actuals, as_of=date(2026, 3, 1), min_observations=1)
    assert set(after_q1) == {"sharp", "sloppy"}
    # Only after Q2 is announced do both analysts clear the two-observation bar.
    assert set(analyst_accuracy(estimates, actuals, as_of=date(2026, 6, 1))) == {"sharp", "sloppy"}


def test_estimates_published_after_the_announcement_are_not_forecasts() -> None:
    # An "estimate" filed after earnings are out is hindsight, not skill.
    estimates = [
        _est("cheater", 1.00, "2026-02-15"),  # filed AFTER the 2026-02-01 announcement
        _est("honest", 1.20, "2026-01-10"),
        _est("other", 1.40, "2026-01-10"),  # keeps a real cross-section to rank within
    ]
    actuals = [_act(1.00, "2026-02-01")]
    scores = analyst_accuracy(estimates, actuals, as_of=date(2026, 6, 1), min_observations=1)
    assert "cheater" not in scores  # a perfect post-hoc "forecast" earns nothing
    assert scores["honest"] > scores["other"]


def test_only_the_latest_pre_announcement_estimate_counts() -> None:
    estimates = [
        _est("a", 5.00, "2026-01-02"),  # stale, wildly wrong
        _est("a", 1.01, "2026-01-20"),  # their final call before earnings
        _est("b", 1.30, "2026-01-20"),
    ]
    actuals = [_act(1.00, "2026-02-01")]
    scores = analyst_accuracy(estimates, actuals, as_of=date(2026, 6, 1), min_observations=1)
    assert scores["a"] > scores["b"]  # judged on the 1.01 call, not the stale 5.00


def test_analyst_below_minimum_observations_is_omitted() -> None:
    estimates, actuals = _two_periods()
    estimates.append(_est("rookie", 1.10, "2026-04-10", fq=2))
    scores = analyst_accuracy(estimates, actuals, as_of=date(2026, 6, 1), min_observations=2)
    assert "rookie" not in scores  # one observation is not a track record


def test_no_actuals_yields_no_scores() -> None:
    estimates, _ = _two_periods()
    assert analyst_accuracy(estimates, [], as_of=date(2026, 6, 1)) == {}


def test_single_analyst_period_is_not_scored_by_rank() -> None:
    # With one analyst there is no cross-section to rank against; that period is skipped
    # rather than inventing a percentile.
    estimates = [_est("solo", 1.05, "2026-01-10")]
    actuals = [_act(1.00, "2026-02-01")]
    assert analyst_accuracy(estimates, actuals, as_of=date(2026, 6, 1), min_observations=1) == {}


def test_default_minimum_is_conservative() -> None:
    assert MIN_OBSERVATIONS >= 2


# ------------------------------------------------------------------------- enrichment


def test_enrichment_sets_accuracy_and_leaves_other_fields_intact() -> None:
    estimates = [_est("sharp", 1.0, "2026-01-10"), _est("unknown", 1.0, "2026-01-10")]
    out = enrich_with_accuracy(estimates, {"sharp": 0.9}, default=0.5)
    by = {e.analyst_id: e for e in out}
    assert by["sharp"].analyst_accuracy == 0.9
    assert by["unknown"].analyst_accuracy == 0.5  # prior for analysts with no record
    assert by["sharp"].value == 1.0
    assert by["sharp"].estimate_date == date(2026, 1, 10)


def test_enrichment_does_not_mutate_the_inputs() -> None:
    estimates = [_est("sharp", 1.0, "2026-01-10")]
    enrich_with_accuracy(estimates, {"sharp": 0.9})
    assert estimates[0].analyst_accuracy is None  # contracts are frozen


def test_enrichment_rejects_out_of_range_accuracy() -> None:
    with pytest.raises(ValueError, match="accuracy"):
        enrich_with_accuracy([_est("a", 1.0, "2026-01-10")], {"a": 1.5})
