"""Data contracts: Pydantic models enforced at every module boundary (DATA_CONTRACTS.md).

These are enforced at runtime. Any function that takes or returns financial data must
use these types in its signature — no raw dicts or DataFrames cross a module boundary
without being validated through a schema first (PRINCIPLES.md Rule 5 & Rule 12).

All contracts are ``frozen`` (immutable) and ``extra="forbid"`` (unknown fields are an
error), enforcing the Golden Rule: no shared mutable state, fail fast on bad data.
"""

from __future__ import annotations

import re
from datetime import date
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class _Contract(BaseModel):
    """Base class for all data contracts: immutable, strict, whitespace-trimmed."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class DataSourceName(str, Enum):
    """Where a record came from. ``fixture`` = synthetic test data, not for production."""

    factset = "factset"
    backup = "backup"
    fixture = "fixture"


class Metric(str, Enum):
    """Estimate metric type."""

    eps = "EPS"
    revenue = "Revenue"
    ebitda = "EBITDA"
    ebit = "EBIT"
    net_income = "NetIncome"
    fcf = "FCF"


class SignalStatus(str, Enum):
    """Signal lifecycle state (SIGNAL_REGISTRY.md)."""

    discovered = "DISCOVERED"
    validated = "VALIDATED"
    staging = "STAGING"
    production = "PRODUCTION"
    retired = "RETIRED"


# ---------------------------------------------------------------------------- prices
class PriceData(_Contract):
    """A single ticker's OHLCV bar for one date."""

    ticker: str = Field(min_length=1, max_length=12)
    date: date
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)
    adjusted_close: float = Field(gt=0)
    data_source: DataSourceName
    point_in_time: bool

    @field_validator("ticker")
    @classmethod
    def _uppercase_ticker(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _check_ohlc_consistency(self) -> PriceData:
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) < low ({self.low})")
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"open ({self.open}) outside [low={self.low}, high={self.high}]")
        if not (self.low <= self.close <= self.high):
            raise ValueError(f"close ({self.close}) outside [low={self.low}, high={self.high}]")
        return self


# ------------------------------------------------------------------------- estimates
class EstimateData(_Contract):
    """One analyst's estimate of one metric for one fiscal period."""

    ticker: str = Field(min_length=1, max_length=12)
    analyst_id: str = Field(min_length=1)
    broker: str = Field(min_length=1)
    estimate_date: date
    fiscal_year: int = Field(ge=1990, le=2100)
    fiscal_quarter: int = Field(ge=1, le=4)
    metric: Metric
    value: float
    currency: str = Field(min_length=3, max_length=3)
    is_point_in_time: bool
    # Optional enrichment: this analyst's historical accuracy on this metric, 0..1.
    analyst_accuracy: float | None = Field(default=None, ge=0, le=1)

    @field_validator("ticker", "currency")
    @classmethod
    def _uppercase(cls, v: str) -> str:
        return v.upper()


# ---------------------------------------------------------------------- signal score
class SignalScore(_Contract):
    """A signal's output for one ticker on one date."""

    ticker: str = Field(min_length=1, max_length=12)
    date: date
    signal_name: str = Field(min_length=1)
    signal_version: str  # semver, e.g. "1.0.0"
    raw_score: float
    rank_score: float = Field(ge=0, le=1)  # cross-sectional rank 0..1
    ic_trailing_90d: float | None = None
    data_inputs: list[str] = Field(min_length=1)

    @field_validator("signal_version")
    @classmethod
    def _check_semver(cls, v: str) -> str:
        if not _SEMVER_RE.match(v):
            raise ValueError(f"signal_version must be semver MAJOR.MINOR.PATCH, got {v!r}")
        return v


# ------------------------------------------------------------------- backtest result
class BacktestResult(_Contract):
    """The outcome of validating one signal over a date range."""

    signal_name: str = Field(min_length=1)
    start_date: date
    end_date: date
    mean_ic: float
    ic_std: float = Field(ge=0)
    icir: float
    t_statistic: float
    p_value: float = Field(ge=0, le=1)
    positive_ic_ratio: float = Field(ge=0, le=1)
    annualized_return: float
    max_drawdown: float = Field(le=0)  # drawdown is non-positive
    sharpe_ratio: float
    regime_results: dict[str, float]  # regime name -> IC in that regime
    passed_validation: bool
    failure_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_dates_and_reasons(self) -> BacktestResult:
        if self.end_date < self.start_date:
            raise ValueError(f"end_date ({self.end_date}) before start_date ({self.start_date})")
        if self.passed_validation and self.failure_reasons:
            raise ValueError("passed_validation=True but failure_reasons is non-empty")
        if not self.passed_validation and not self.failure_reasons:
            raise ValueError("passed_validation=False requires at least one failure reason")
        return self


# ----------------------------------------------------------------- portfolio weights
class PortfolioWeights(_Contract):
    """Target portfolio weights for one rebalance date."""

    date: date
    weights: dict[str, float]  # ticker -> weight in [-1, 1]
    expected_return: float
    expected_cvar: float
    turnover: float = Field(ge=0)
    construction_method: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check_weight_bounds(self) -> PortfolioWeights:
        for ticker, w in self.weights.items():
            if not (-1.0 <= w <= 1.0):
                raise ValueError(f"weight for {ticker} ({w}) outside [-1, 1]")
        return self


class Relationship(str, Enum):
    """Direction of a supply-chain relationship, relative to the subject ticker."""

    supplier = "supplier"
    customer = "customer"


# ---------------------------------------------------------------------- fundamentals
class FundamentalData(_Contract):
    """Point-in-time fundamentals for one ticker for one fiscal period."""

    ticker: str = Field(min_length=1, max_length=12)
    report_date: date  # date the figures became available (point-in-time)
    fiscal_year: int = Field(ge=1990, le=2100)
    fiscal_quarter: int = Field(ge=1, le=4)
    total_assets: float = Field(gt=0)
    net_income: float
    operating_cash_flow: float
    revenue: float = Field(ge=0)
    is_point_in_time: bool

    @field_validator("ticker")
    @classmethod
    def _uppercase_ticker(cls, v: str) -> str:
        return v.upper()


# ------------------------------------------------------------------------- ownership
class OwnershipData(_Contract):
    """Institutional-ownership snapshot for one ticker on one date."""

    ticker: str = Field(min_length=1, max_length=12)
    as_of_date: date
    institutional_ownership_pct: float = Field(ge=0, le=1)  # fraction of shares held
    institution_count: int = Field(ge=0)
    is_point_in_time: bool

    @field_validator("ticker")
    @classmethod
    def _uppercase_ticker(cls, v: str) -> str:
        return v.upper()


# ----------------------------------------------------------------------- supply chain
class SupplyChainLink(_Contract):
    """A directed supplier/customer relationship between two tickers."""

    ticker: str = Field(min_length=1, max_length=12)
    related_ticker: str = Field(min_length=1, max_length=12)
    relationship: Relationship
    weight: float = Field(ge=0, le=1)  # relationship strength (e.g. revenue share)
    is_point_in_time: bool

    @field_validator("ticker", "related_ticker")
    @classmethod
    def _uppercase(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _check_not_self(self) -> SupplyChainLink:
        if self.ticker == self.related_ticker:
            raise ValueError(f"supply-chain link points to itself: {self.ticker}")
        return self
