"""Point-in-time analyst accuracy — the "expert" half of TrueBeats.

A consensus average treats every analyst as equally informative. TrueBeats does not: it
weights each forecast by how well that analyst has actually predicted this metric before,
and the gap between the accuracy-weighted consensus and the naive one is the predicted
surprise. This module computes that accuracy, and it is a prime look-ahead hazard, so the
rules are strict:

* **An actual only counts once announced.** Accuracy as of date *d* may use a realized
  figure only if ``announced_date <= d``. Using a result before it was public would
  manufacture skill out of hindsight.
* **Only pre-announcement estimates are forecasts.** An estimate filed after earnings are
  out is not a prediction, and is excluded.
* **One call per analyst per period** — their LAST estimate before the announcement.
* **Rank-based, per period.** Errors are converted to a within-period percentile so that
  a high-EPS company cannot dominate the score through scale alone; periods with a single
  analyst are skipped rather than inventing a percentile.

Accuracy is in ``[0, 1]`` (1 = most accurate), matching ``EstimateData.analyst_accuracy``.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from src.monitoring.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from src.data.contracts.schemas import ActualData, EstimateData

_log = get_logger(__name__)

#: Minimum scored periods before an analyst gets a track record (below this the caller's
#: prior is used). Two is the floor at which a mean is not simply one lucky call.
MIN_OBSERVATIONS = 2

#: Prior for analysts with no usable history — deliberately neutral.
DEFAULT_ACCURACY = 0.5


def analyst_accuracy(
    estimates: Sequence[EstimateData],
    actuals: Sequence[ActualData],
    as_of: date,
    *,
    min_observations: int = MIN_OBSERVATIONS,
) -> dict[str, float]:
    """Score each analyst's historical forecast accuracy, point-in-time as of ``as_of``.

    Args:
        estimates: Individual analyst estimates (any tickers/periods).
        actuals: Realized figures; only those announced on or before ``as_of`` are used.
        as_of: The date the score is computed for.
        min_observations: Minimum scored periods required to report an analyst.

    Returns:
        ``analyst_id -> accuracy`` in [0, 1]; analysts without enough history are absent.
    """
    known = {
        (a.ticker.upper(), a.fiscal_year, a.fiscal_quarter): a
        for a in actuals
        if a.announced_date <= as_of  # PIT: unannounced results do not exist yet
    }
    if not known:
        return {}

    # period -> analyst -> their last estimate BEFORE the announcement
    per_period: dict[tuple[str, int, int], dict[str, EstimateData]] = defaultdict(dict)
    for est in estimates:
        key = (est.ticker.upper(), est.fiscal_year, est.fiscal_quarter)
        actual = known.get(key)
        if actual is None or est.estimate_date >= actual.announced_date:
            continue  # no result yet, or filed after the fact (hindsight, not a forecast)
        seen = per_period[key].get(est.analyst_id)
        if seen is None or est.estimate_date > seen.estimate_date:
            per_period[key][est.analyst_id] = est

    scores: dict[str, list[float]] = defaultdict(list)
    for key, by_analyst in per_period.items():
        if len(by_analyst) < 2:
            continue  # no cross-section to rank within
        actual_value = known[key].value
        ranked = sorted(by_analyst.items(), key=lambda kv: abs(kv[1].value - actual_value))
        last = len(ranked) - 1
        for position, (analyst_id, _) in enumerate(ranked):
            scores[analyst_id].append(1.0 - position / last)  # best error -> 1.0

    out = {
        analyst_id: sum(values) / len(values)
        for analyst_id, values in scores.items()
        if len(values) >= min_observations
    }
    _log.info(
        "accuracy.scored",
        as_of=str(as_of),
        analysts=len(out),
        periods=len(per_period),
        min_observations=min_observations,
    )
    return out


def enrich_with_accuracy(
    estimates: Sequence[EstimateData],
    accuracy: Mapping[str, float],
    *,
    default: float = DEFAULT_ACCURACY,
) -> list[EstimateData]:
    """Return copies of ``estimates`` carrying each analyst's accuracy.

    Args:
        estimates: Estimates to enrich (never mutated — contracts are frozen).
        accuracy: ``analyst_id -> accuracy`` from :func:`analyst_accuracy`.
        default: Prior applied to analysts absent from ``accuracy``.

    Returns:
        New :class:`EstimateData` objects with ``analyst_accuracy`` populated.

    Raises:
        ValueError: if any supplied accuracy falls outside [0, 1].
    """
    for analyst_id, value in accuracy.items():
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"accuracy for {analyst_id} is {value}; must be within [0, 1]")
    if not 0.0 <= default <= 1.0:
        raise ValueError(f"default accuracy {default} must be within [0, 1]")
    return [
        est.model_copy(update={"analyst_accuracy": accuracy.get(est.analyst_id, default)})
        for est in estimates
    ]
