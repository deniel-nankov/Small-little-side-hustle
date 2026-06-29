"""Signal-decay test (Milestone 3): does IC persist at longer forward horizons?

Validation test #4. A signal with real edge keeps predicting at a longer horizon; one that
only works at a 1-month horizon and vanishes by 3 months is likely overfit or a
short-lived effect. We recompute the IC against a longer forward-return horizon and require
it to stay above a (lower) threshold.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from src.data.contracts.schemas import PriceData, SignalScore
from src.signals.validation.ic_calculator import (
    MIN_CROSS_SECTION_SIZE,
    compute_forward_returns,
    daily_ics,
)

#: Forward horizon at which longevity is checked (~3 months of trading days).
DECAY_HORIZON_DAYS = 63

#: Minimum mean IC required at the decay horizon to pass.
DECAY_IC_THRESHOLD = 0.01


class DecayTestResult(BaseModel):
    """Outcome of the decay test."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    horizon_days: int = Field(gt=0)
    threshold: float
    mean_ic: float
    n_periods: int = Field(ge=0)
    passed: bool


def decay_test(
    scores: Sequence[SignalScore],
    prices: Sequence[PriceData],
    horizon_days: int = DECAY_HORIZON_DAYS,
    ic_threshold: float = DECAY_IC_THRESHOLD,
    min_cross_section: int = MIN_CROSS_SECTION_SIZE,
) -> DecayTestResult:
    """Check that the signal's IC survives at a longer forward horizon.

    Args:
        scores: Signal scores across tickers and dates.
        prices: Price bars used to compute long-horizon forward returns.
        horizon_days: Forward horizon in trading observations.
        ic_threshold: Minimum mean IC required to pass.
        min_cross_section: Minimum names required to score a date.

    Returns:
        A :class:`DecayTestResult`.

    Raises:
        ValueError: if no date had a computable IC at the decay horizon.
    """
    forward_returns: Mapping[tuple[str, date], float] = compute_forward_returns(
        prices, horizon_days
    )
    series = daily_ics(scores, forward_returns, min_cross_section)
    if not series:
        raise ValueError("no date had a computable IC at the decay horizon")
    mean_ic = statistics.fmean(ic for _, ic in series)
    return DecayTestResult(
        horizon_days=horizon_days,
        threshold=ic_threshold,
        mean_ic=mean_ic,
        n_periods=len(series),
        passed=mean_ic > ic_threshold,
    )
