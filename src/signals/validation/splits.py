"""Train/test split discipline for signal validation (Stage C, #32).

Enforces the out-of-sample non-negotiable: whatever window a signal was tuned on
(in-sample / "train"), its acceptance evidence must come from a strictly later,
non-overlapping window (out-of-sample / "test").

Rules, enforced by construction — violations raise :class:`SplitError`, never warn:

* **Chronological only.** Test data is strictly after train data. No shuffled or
  interleaved splits: financial data is autocorrelated and regimes cluster in time.
* **Embargo gap.** The windows are separated by ``embargo_days``: a score on the last
  train day is evaluated against forward returns reaching up to 21 trading days
  (~:data:`DEFAULT_EMBARGO_DAYS` calendar days) ahead — without the gap, train
  evaluation would peek into test-window prices.
* **Boundaries are inclusive**; records inside the embargo gap belong to NEITHER side.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, TypeVar

from src.utils.pit import knowledge_date

if TYPE_CHECKING:
    from collections.abc import Iterable

T = TypeVar("T")

#: Default gap between train and test: covers the 21-trading-day forward-return horizon
#: (~30 calendar days) used by the IC evaluation, so train scores never see test prices.
DEFAULT_EMBARGO_DAYS = 30

#: Default share of the span given to the test window.
DEFAULT_TEST_FRACTION = 0.3

#: Minimum days each window must span for the evaluation to be meaningful.
_MIN_WINDOW_DAYS = 21


class SplitError(ValueError):
    """Raised when a train/test split would violate out-of-sample discipline."""


@dataclass(frozen=True)
class TrainTestSplit:
    """Chronological in-sample / out-of-sample windows (all boundaries inclusive)."""

    train_start: date
    train_end: date
    test_start: date
    test_end: date

    def __post_init__(self) -> None:
        """Validate ordering and disjointness; raise :class:`SplitError` otherwise."""
        if self.train_end < self.train_start:
            raise SplitError(
                f"train window inverted: {self.train_start} .. {self.train_end}"
            )
        if self.test_end < self.test_start:
            raise SplitError(f"test window inverted: {self.test_start} .. {self.test_end}")
        if self.test_start <= self.train_end:
            raise SplitError(
                f"windows overlap: train ends {self.train_end}, test starts "
                f"{self.test_start} — test must be strictly after train"
            )

    @property
    def embargo_days(self) -> int:
        """Calendar days of gap between the train and test windows."""
        return (self.test_start - self.train_end).days - 1


def make_train_test_split(
    start: date,
    end: date,
    *,
    test_fraction: float = DEFAULT_TEST_FRACTION,
    embargo_days: int = DEFAULT_EMBARGO_DAYS,
) -> TrainTestSplit:
    """Split ``[start, end]`` chronologically into train + embargo + test.

    Args:
        start: First day of the full span (becomes ``train_start``).
        end: Last day of the full span (becomes ``test_end``).
        test_fraction: Share of the span given to the test window, in (0, 1).
        embargo_days: Calendar days of gap between the windows (>= 0).

    Returns:
        A validated :class:`TrainTestSplit`.

    Raises:
        SplitError: on bad fraction/embargo, or a span too short to fit both windows.
    """
    if not 0.0 < test_fraction < 1.0:
        raise SplitError(f"test_fraction must be in (0, 1), got {test_fraction}")
    if embargo_days < 0:
        raise SplitError(f"embargo_days must be >= 0, got {embargo_days}")
    if end < start:
        raise SplitError(f"end ({end}) precedes start ({start})")

    span_days = (end - start).days
    test_days = round(span_days * test_fraction)
    test_start = end - timedelta(days=test_days)
    train_end = test_start - timedelta(days=embargo_days + 1)
    if (train_end - start).days < _MIN_WINDOW_DAYS or test_days < _MIN_WINDOW_DAYS:
        raise SplitError(
            f"span {start} .. {end} too short for test_fraction={test_fraction} + "
            f"embargo={embargo_days}d (each window needs >= {_MIN_WINDOW_DAYS} days)"
        )
    return TrainTestSplit(
        train_start=start, train_end=train_end, test_start=test_start, test_end=end
    )


def split_by_date(records: Iterable[T], split: TrainTestSplit) -> tuple[list[T], list[T]]:
    """Partition dated records into (train, test); embargo-gap records go to neither.

    Args:
        records: Records carrying a knowledge date (see :func:`knowledge_date`).
        split: The windows to partition by.

    Returns:
        ``(train, test)`` lists, input order preserved.
    """
    train: list[T] = []
    test: list[T] = []
    for record in records:
        day = knowledge_date(record)
        if split.train_start <= day <= split.train_end:
            train.append(record)
        elif split.test_start <= day <= split.test_end:
            test.append(record)
    return train, test


def assert_out_of_sample(
    train: Iterable[Any], test: Iterable[Any], *, embargo_days: int = 0
) -> None:
    """Hard-fail unless every test record is strictly after every train record.

    Args:
        train: In-sample records (any objects with a knowledge date).
        test: Out-of-sample records.
        embargo_days: Minimum calendar-day gap required between the sides.

    Raises:
        SplitError: if the sides overlap or the gap is smaller than the embargo.
    """
    train_dates = [knowledge_date(r) for r in train]
    test_dates = [knowledge_date(r) for r in test]
    if not train_dates or not test_dates:
        return
    train_max, test_min = max(train_dates), min(test_dates)
    gap = (test_min - train_max).days - 1
    if test_min <= train_max:
        raise SplitError(
            f"out-of-sample violation: test data starts {test_min}, on or before the "
            f"last train date {train_max}"
        )
    if gap < embargo_days:
        raise SplitError(
            f"embargo violation: only {gap} gap day(s) between train ({train_max}) and "
            f"test ({test_min}); {embargo_days} required"
        )
