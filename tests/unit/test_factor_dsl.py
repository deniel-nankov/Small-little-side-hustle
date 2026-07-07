"""Unit tests for the factor expression DSL (Stage 4, #52).

The DSL is the shared foundation of every discovery engine (NVIDIA blueprint /
AlphaAgent / QuantaAlpha all mine operator trees over market data), so its math is
hand-verified here on tiny panels.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest
from src.signals.discovery.factor_dsl import (
    Binary,
    Feature,
    TimeSeries,
    Unary,
    node_count,
    panel_from_prices,
    param_count,
    parse,
    random_expression,
    similarity,
    to_scores,
)

from tests.synth import flat_bar

_D0 = date(2026, 3, 2)


def _panel(closes_by_ticker: dict[str, list[float]]):  # noqa: ANN202
    bars = []
    for ticker, closes in closes_by_ticker.items():
        for i, close in enumerate(closes):
            bars.append(flat_bar(ticker, _D0 + timedelta(days=i), close))
    return panel_from_prices(bars)


# ------------------------------------------------------------------- panel + features


def test_panel_aligns_and_fills_missing_with_nan() -> None:
    panel = _panel({"A": [100.0, 101.0, 102.0]})
    bars_b = [flat_bar("B", _D0, 50.0), flat_bar("B", _D0 + timedelta(days=2), 52.0)]
    full = panel_from_prices(
        [flat_bar("A", _D0 + timedelta(days=i), 100.0 + i) for i in range(3)] + bars_b
    )
    assert full.dates == panel.dates
    series_b = Feature("close").evaluate(full)["B"]
    assert series_b[0] == 50.0
    assert math.isnan(series_b[1])  # B missing on day 2
    assert series_b[2] == 52.0


def test_returns_feature_is_pct_change_with_warmup_nan() -> None:
    panel = _panel({"A": [100.0, 110.0, 99.0]})
    ret = Feature("ret").evaluate(panel)["A"]
    assert math.isnan(ret[0])
    assert ret[1] == pytest.approx(0.10)
    assert ret[2] == pytest.approx(99.0 / 110.0 - 1.0)


def test_unknown_feature_raises() -> None:
    with pytest.raises(ValueError, match="unknown feature"):
        Feature("pe_ratio").evaluate(_panel({"A": [1.0]}))


# ------------------------------------------------------------------------- operators


def test_delta_and_delay() -> None:
    panel = _panel({"A": [10.0, 12.0, 15.0]})
    delayed = TimeSeries("delay", Feature("close"), 1).evaluate(panel)["A"]
    assert math.isnan(delayed[0]) and delayed[1:] == [10.0, 12.0]
    delta = TimeSeries("delta", Feature("close"), 2).evaluate(panel)["A"]
    assert math.isnan(delta[0]) and math.isnan(delta[1]) and delta[2] == 5.0


def test_ts_mean_and_ts_std() -> None:
    panel = _panel({"A": [1.0, 2.0, 3.0, 4.0]})
    mean = TimeSeries("ts_mean", Feature("close"), 2).evaluate(panel)["A"]
    assert math.isnan(mean[0]) and mean[1:] == [1.5, 2.5, 3.5]
    std = TimeSeries("ts_std", Feature("close"), 3).evaluate(panel)["A"]
    assert std[2] == pytest.approx(1.0)  # sample std of 1,2,3


def test_momentum() -> None:
    panel = _panel({"A": [100.0, 7.0, 13.0, 110.0]})
    mom = TimeSeries("momentum", Feature("close"), 3).evaluate(panel)["A"]
    assert mom[3] == pytest.approx(0.10)  # 110/100 - 1, ignoring the middle noise


def test_safe_div_yields_nan_on_zero_denominator() -> None:
    panel = _panel({"A": [1.0, 2.0]})
    expr = Binary("div", Feature("close"), Binary("sub", Feature("close"), Feature("close")))
    values = expr.evaluate(panel)["A"]
    assert all(math.isnan(v) for v in values)


def test_cs_rank_is_uniform_in_zero_one_per_date() -> None:
    panel = _panel({"A": [1.0, 9.0], "B": [2.0, 5.0], "C": [3.0, 1.0]})
    ranks = Unary("cs_rank", Feature("close")).evaluate(panel)
    day0 = [ranks["A"][0], ranks["B"][0], ranks["C"][0]]
    assert day0 == sorted(day0) and min(day0) == 0.0 and max(day0) == 1.0
    assert ranks["C"][1] == 0.0 and ranks["A"][1] == 1.0  # order flipped on day 1


def test_cs_zscore_centers_the_cross_section() -> None:
    panel = _panel({"A": [1.0], "B": [2.0], "C": [3.0]})
    z = Unary("cs_zscore", Feature("close")).evaluate(panel)
    assert z["B"][0] == pytest.approx(0.0)
    assert z["A"][0] == pytest.approx(-z["C"][0])


def test_nan_propagates_through_operators() -> None:
    panel = _panel({"A": [1.0, 2.0, 3.0]})
    expr = Binary("add", TimeSeries("delay", Feature("close"), 1), Feature("close"))
    assert math.isnan(expr.evaluate(panel)["A"][0])


def test_unknown_operator_raises() -> None:
    panel = _panel({"A": [1.0]})
    with pytest.raises(ValueError, match="unknown"):
        Unary("sqrtish", Feature("close")).evaluate(panel)


# ------------------------------------------------------------- serialization + parse


def test_serialization_roundtrip() -> None:
    expr = Binary(
        "div",
        TimeSeries("delta", Feature("close"), 5),
        TimeSeries("ts_std", Feature("ret"), 21),
    )
    assert str(expr) == "(div (delta close 5) (ts_std ret 21))"
    assert parse(str(expr)) == expr


def test_parse_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="parse"):
        parse("(frobnicate close 5")


# --------------------------------------------------------------- metrics + similarity


def test_node_and_param_counts() -> None:
    expr = Binary(
        "div",
        TimeSeries("delta", Feature("close"), 5),
        TimeSeries("ts_std", Feature("ret"), 21),
    )
    assert node_count(expr) == 5  # div, delta, close, ts_std, ret
    assert param_count(expr) == 2  # the two windows


def test_similarity_identical_and_disjoint() -> None:
    a = TimeSeries("delta", Feature("close"), 5)
    b = TimeSeries("delta", Feature("close"), 5)
    c = Unary("abs", Feature("volume"))
    assert similarity(a, b) == node_count(a)
    assert similarity(a, c) == 0
    assert similarity(a, c) == similarity(c, a)  # symmetric


def test_similarity_finds_shared_subtree() -> None:
    shared = TimeSeries("ts_mean", Feature("ret"), 10)
    a = Binary("add", shared, Feature("close"))
    b = Binary("mul", shared, Feature("volume"))
    assert similarity(a, b) == node_count(shared)


# ------------------------------------------------------------------ random generation


def test_random_expression_is_deterministic_and_bounded() -> None:
    import random

    e1 = random_expression(random.Random(7), max_depth=4)
    e2 = random_expression(random.Random(7), max_depth=4)
    assert e1 == e2
    assert node_count(e1) >= 1


def test_random_expressions_evaluate_without_crashing() -> None:
    import random

    panel = _panel({"A": [100.0 + i for i in range(30)], "B": [50.0 - i * 0.1 for i in range(30)]})
    for seed in range(20):
        expr = random_expression(random.Random(seed), max_depth=4)
        values = expr.evaluate(panel)
        assert set(values) == {"A", "B"}
        assert all(len(v) == 30 for v in values.values())


# -------------------------------------------------------------------------- to_scores


def test_to_scores_builds_valid_signal_scores_and_skips_nan() -> None:
    panel = _panel({"A": [1.0, 2.0, 3.0], "B": [3.0, 2.0, 1.0], "C": [2.0, 2.0, 2.0]})
    expr = TimeSeries("delta", Feature("close"), 1)  # nan on day 0
    scores = to_scores(expr, panel, signal_name="dsl_test", signal_version="0.1.0")
    days = {s.date for s in scores}
    assert _D0 not in days  # warmup day skipped entirely
    assert all(0.0 <= s.rank_score <= 1.0 for s in scores)
    assert all(s.signal_name == "dsl_test" for s in scores)
    assert len(scores) == 6  # 3 tickers x 2 valid days
