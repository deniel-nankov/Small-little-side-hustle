"""Unit tests for train/test split discipline (Stage C, #32).

The rules being pinned:

* Chronological only — test data is strictly AFTER train data, never interleaved.
* An embargo gap separates the windows: the last train scores' forward returns
  (21 trading days for IC) must not reach into the test window.
* Overlap of any kind raises ``SplitError`` — never silently reshuffles.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from src.data.contracts.schemas import FundamentalData
from src.signals.validation.splits import (
    DEFAULT_EMBARGO_DAYS,
    SplitError,
    TrainTestSplit,
    assert_out_of_sample,
    make_train_test_split,
    split_by_date,
)

from tests.synth import flat_bar

_START = date(2024, 7, 1)
_END = date(2026, 6, 30)


# ------------------------------------------------------------------ TrainTestSplit


def test_valid_split_constructs() -> None:
    split = TrainTestSplit(
        train_start=date(2024, 1, 1),
        train_end=date(2024, 12, 31),
        test_start=date(2025, 2, 1),
        test_end=date(2025, 6, 30),
    )
    assert split.embargo_days == 31  # gap between 2024-12-31 and 2025-02-01


def test_overlapping_windows_raise() -> None:
    with pytest.raises(SplitError, match="overlap"):
        TrainTestSplit(
            train_start=date(2024, 1, 1),
            train_end=date(2025, 3, 1),
            test_start=date(2025, 2, 1),
            test_end=date(2025, 6, 30),
        )


def test_inverted_train_window_raises() -> None:
    with pytest.raises(SplitError, match="train"):
        TrainTestSplit(
            train_start=date(2024, 6, 1),
            train_end=date(2024, 1, 1),
            test_start=date(2025, 1, 1),
            test_end=date(2025, 6, 30),
        )


def test_inverted_test_window_raises() -> None:
    with pytest.raises(SplitError, match="test"):
        TrainTestSplit(
            train_start=date(2024, 1, 1),
            train_end=date(2024, 6, 1),
            test_start=date(2025, 6, 30),
            test_end=date(2025, 1, 1),
        )


# ------------------------------------------------------- make_train_test_split


def test_make_split_covers_range_with_embargo() -> None:
    split = make_train_test_split(_START, _END)
    assert split.train_start == _START
    assert split.test_end == _END
    assert split.embargo_days == DEFAULT_EMBARGO_DAYS
    assert split.train_end < split.test_start


def test_make_split_test_fraction_sizes_test_window() -> None:
    split = make_train_test_split(_START, _END, test_fraction=0.5)
    span = (_END - _START).days
    test_len = (split.test_end - split.test_start).days
    assert abs(test_len - span * 0.5) <= 2  # rounding tolerance


@pytest.mark.parametrize("fraction", [0.0, 1.0, -0.1, 1.5])
def test_make_split_rejects_bad_fraction(fraction: float) -> None:
    with pytest.raises(SplitError, match="test_fraction"):
        make_train_test_split(_START, _END, test_fraction=fraction)


def test_make_split_rejects_negative_embargo() -> None:
    with pytest.raises(SplitError, match="embargo"):
        make_train_test_split(_START, _END, embargo_days=-1)


def test_make_split_rejects_too_short_span() -> None:
    with pytest.raises(SplitError, match="too short"):
        make_train_test_split(_START, _START + timedelta(days=40), test_fraction=0.3)


# ----------------------------------------------------------------- split_by_date


def _split_fixture() -> TrainTestSplit:
    return TrainTestSplit(
        train_start=date(2026, 1, 1),
        train_end=date(2026, 3, 31),
        test_start=date(2026, 5, 1),
        test_end=date(2026, 6, 30),
    )


def test_split_by_date_partitions_and_drops_embargo() -> None:
    split = _split_fixture()
    bars = [
        flat_bar("A", date(2026, 2, 1), 100.0),  # train
        flat_bar("A", date(2026, 3, 31), 101.0),  # train boundary (inclusive)
        flat_bar("A", date(2026, 4, 15), 102.0),  # embargo gap -> dropped
        flat_bar("A", date(2026, 5, 1), 103.0),  # test boundary (inclusive)
        flat_bar("A", date(2026, 6, 1), 104.0),  # test
    ]
    train, test = split_by_date(bars, split)
    assert [b.date for b in train] == [date(2026, 2, 1), date(2026, 3, 31)]
    assert [b.date for b in test] == [date(2026, 5, 1), date(2026, 6, 1)]


def test_split_by_date_uses_knowledge_date_for_fundamentals() -> None:
    split = _split_fixture()
    row = FundamentalData(
        ticker="AAPL",
        report_date=date(2026, 5, 15),  # knowledge date -> test window
        fiscal_year=2026,
        fiscal_quarter=2,
        total_assets=1.0,
        net_income=1.0,
        operating_cash_flow=1.0,
        revenue=1.0,
        is_point_in_time=True,
    )
    train, test = split_by_date([row], split)
    assert train == []
    assert test == [row]


def test_split_by_date_empty_input() -> None:
    assert split_by_date([], _split_fixture()) == ([], [])


# ----------------------------------------------------------- assert_out_of_sample


def test_assert_out_of_sample_passes_when_disjoint() -> None:
    train = [flat_bar("A", date(2026, 1, 10), 100.0)]
    test = [flat_bar("A", date(2026, 3, 10), 101.0)]
    assert_out_of_sample(train, test)  # must not raise


def test_assert_out_of_sample_raises_on_overlap() -> None:
    train = [flat_bar("A", date(2026, 3, 10), 100.0)]
    test = [flat_bar("A", date(2026, 3, 10), 101.0)]
    with pytest.raises(SplitError, match="out-of-sample"):
        assert_out_of_sample(train, test)


def test_assert_out_of_sample_enforces_embargo() -> None:
    train = [flat_bar("A", date(2026, 3, 1), 100.0)]
    test = [flat_bar("A", date(2026, 3, 10), 101.0)]  # only 9 days after train max
    with pytest.raises(SplitError, match="embargo"):
        assert_out_of_sample(train, test, embargo_days=30)


def test_assert_out_of_sample_empty_sides_pass() -> None:
    assert_out_of_sample([], [flat_bar("A", date(2026, 3, 1), 100.0)])
    assert_out_of_sample([flat_bar("A", date(2026, 3, 1), 100.0)], [])
