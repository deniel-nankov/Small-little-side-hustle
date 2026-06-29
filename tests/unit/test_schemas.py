"""Unit tests for data contracts (src/data/contracts/schemas.py)."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError
from src.data.contracts.schemas import (
    BacktestResult,
    DataSourceName,
    EstimateData,
    Metric,
    PortfolioWeights,
    PriceData,
    SignalScore,
)


def _valid_price(**overrides: object) -> PriceData:
    kwargs: dict[str, object] = {
        "ticker": "aapl",
        "date": date(2026, 1, 2),
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 1_000_000.0,
        "adjusted_close": 101.0,
        "data_source": DataSourceName.fixture,
        "point_in_time": True,
    }
    kwargs.update(overrides)
    return PriceData(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------- PriceData
def test_price_data_valid_uppercases_ticker() -> None:
    assert _valid_price().ticker == "AAPL"


def test_price_data_is_frozen() -> None:
    price = _valid_price()
    with pytest.raises(ValidationError):
        price.close = 50.0  # type: ignore[misc]


def test_price_data_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        _valid_price(unexpected="x")


def test_price_data_with_high_below_low_raises() -> None:
    with pytest.raises(ValidationError, match="high"):
        _valid_price(high=98.0, low=99.0)


def test_price_data_with_close_outside_range_raises() -> None:
    with pytest.raises(ValidationError, match="close"):
        _valid_price(close=200.0)


def test_price_data_with_negative_price_raises() -> None:
    with pytest.raises(ValidationError):
        _valid_price(open=-1.0)


# ------------------------------------------------------------- EstimateData
def test_estimate_data_valid() -> None:
    est = EstimateData(
        ticker="msft",
        analyst_id="AN001",
        broker="BRK01",
        estimate_date=date(2026, 1, 10),
        fiscal_year=2026,
        fiscal_quarter=1,
        metric=Metric.eps,
        value=2.5,
        currency="usd",
        is_point_in_time=True,
    )
    assert est.currency == "USD"
    assert est.analyst_accuracy is None


def test_estimate_data_with_bad_quarter_raises() -> None:
    with pytest.raises(ValidationError):
        EstimateData(
            ticker="MSFT",
            analyst_id="AN001",
            broker="BRK01",
            estimate_date=date(2026, 1, 10),
            fiscal_year=2026,
            fiscal_quarter=5,
            metric=Metric.eps,
            value=2.5,
            currency="USD",
            is_point_in_time=True,
        )


# -------------------------------------------------------------- SignalScore
def test_signal_score_valid() -> None:
    score = SignalScore(
        ticker="AAPL",
        date=date(2026, 1, 2),
        signal_name="truebeats",
        signal_version="1.0.0",
        raw_score=0.42,
        rank_score=0.9,
        data_inputs=["estimates"],
    )
    assert score.signal_version == "1.0.0"


def test_signal_score_with_bad_semver_raises() -> None:
    with pytest.raises(ValidationError, match="semver"):
        SignalScore(
            ticker="AAPL",
            date=date(2026, 1, 2),
            signal_name="truebeats",
            signal_version="v1",
            raw_score=0.42,
            rank_score=0.9,
            data_inputs=["estimates"],
        )


def test_signal_score_with_rank_above_one_raises() -> None:
    with pytest.raises(ValidationError):
        SignalScore(
            ticker="AAPL",
            date=date(2026, 1, 2),
            signal_name="truebeats",
            signal_version="1.0.0",
            raw_score=0.42,
            rank_score=1.5,
            data_inputs=["estimates"],
        )


# ----------------------------------------------------------- BacktestResult
def _valid_backtest(**overrides: object) -> BacktestResult:
    kwargs: dict[str, object] = {
        "signal_name": "truebeats",
        "start_date": date(2024, 1, 1),
        "end_date": date(2025, 1, 1),
        "mean_ic": 0.03,
        "ic_std": 0.05,
        "icir": 0.6,
        "t_statistic": 3.1,
        "p_value": 0.01,
        "positive_ic_ratio": 0.6,
        "annualized_return": 0.12,
        "max_drawdown": -0.08,
        "sharpe_ratio": 1.4,
        "regime_results": {"bull": 0.04, "bear": 0.02},
        "passed_validation": True,
        "failure_reasons": [],
    }
    kwargs.update(overrides)
    return BacktestResult(**kwargs)  # type: ignore[arg-type]


def test_backtest_result_valid() -> None:
    assert _valid_backtest().passed_validation is True


def test_backtest_result_passed_with_failure_reasons_raises() -> None:
    with pytest.raises(ValidationError, match="failure_reasons"):
        _valid_backtest(passed_validation=True, failure_reasons=["ic too low"])


def test_backtest_result_failed_without_reasons_raises() -> None:
    with pytest.raises(ValidationError, match="failure reason"):
        _valid_backtest(passed_validation=False, failure_reasons=[])


def test_backtest_result_end_before_start_raises() -> None:
    with pytest.raises(ValidationError, match="before start_date"):
        _valid_backtest(start_date=date(2025, 1, 1), end_date=date(2024, 1, 1))


def test_backtest_result_positive_drawdown_raises() -> None:
    with pytest.raises(ValidationError):
        _valid_backtest(max_drawdown=0.1)


# --------------------------------------------------------- PortfolioWeights
def test_portfolio_weights_valid() -> None:
    pw = PortfolioWeights(
        date=date(2026, 1, 2),
        weights={"AAPL": 0.5, "MSFT": -0.5},
        expected_return=0.02,
        expected_cvar=0.03,
        turnover=0.1,
        construction_method="mean_cvar",
    )
    assert pw.weights["AAPL"] == 0.5


def test_portfolio_weights_out_of_bounds_raises() -> None:
    with pytest.raises(ValidationError, match="outside"):
        PortfolioWeights(
            date=date(2026, 1, 2),
            weights={"AAPL": 1.5},
            expected_return=0.02,
            expected_cvar=0.03,
            turnover=0.1,
            construction_method="mean_cvar",
        )
