"""Deterministic synthetic universes for validation tests (not collected by pytest).

``make_predictive_universe`` builds prices whose forward returns are monotonically related
to a per-ticker drift, plus a matching constant-per-ticker signal — so the signal has
genuine, regime-spanning predictive power. ``make_noise_scores`` returns scores unrelated
to returns.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from src.data.contracts.schemas import DataSourceName, PriceData, SignalScore


def business_days(start: date, n: int) -> list[date]:
    """Return the first ``n`` weekday dates on/after ``start``."""
    days: list[date] = []
    day = start
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def flat_bar(ticker: str, day: date, price: float) -> PriceData:
    """A bar with O=H=L=C=adj=price (trivially OHLC-consistent)."""
    return PriceData(
        ticker=ticker,
        date=day,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=1.0,
        adjusted_close=price,
        data_source=DataSourceName.fixture,
        point_in_time=True,
    )


def make_predictive_universe(
    n_tickers: int = 12,
    n_days: int = 170,
    drift: float = 0.0015,
    noise: float = 0.006,
    seed: str = "bt",
    signal_name: str = "synthpredictive",
) -> tuple[list[SignalScore], list[PriceData]]:
    """Build a predictive (scores, prices) universe.

    Ticker ``i`` has drift ``drift * (i - (n-1)/2)`` (centered, so the market wanders both
    up and down) plus i.i.d. noise; the signal score is ``float(i)``, so higher score
    predicts higher return in every regime.
    """
    days = business_days(date(2026, 1, 1), n_days)
    center = (n_tickers - 1) / 2.0
    prices: list[PriceData] = []
    for i in range(n_tickers):
        rng = random.Random(f"{seed}|{i}")
        price = 100.0
        for t, day in enumerate(days):
            if t > 0:
                price = max(price * (1 + drift * (i - center) + rng.gauss(0.0, noise)), 1.0)
            prices.append(flat_bar(f"T{i:02d}", day, price))

    scores = [
        SignalScore(
            ticker=f"T{i:02d}",
            date=day,
            signal_name=signal_name,
            signal_version="1.0.0",
            raw_score=float(i),
            rank_score=i / (n_tickers - 1),
            data_inputs=["synthetic"],
        )
        for day in days
        for i in range(n_tickers)
    ]
    return scores, prices


def make_noise_scores(
    prices: list[PriceData], seed: str = "noise", signal_name: str = "synthnoise"
) -> list[SignalScore]:
    """Scores re-randomized per (ticker, date), so the IC averages to ~0 (no edge)."""
    tickers = sorted({p.ticker for p in prices})
    dates = sorted({p.date for p in prices})
    return [
        SignalScore(
            ticker=t,
            date=day,
            signal_name=signal_name,
            signal_version="1.0.0",
            raw_score=random.Random(f"{seed}|{t}|{day.isoformat()}").random(),
            rank_score=0.5,
            data_inputs=["synthetic"],
        )
        for day in dates
        for t in tickers
    ]
