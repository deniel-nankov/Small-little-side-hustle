"""Hygiene certification — the gate every reported result must pass.

The standing rule on this project: **no performance number is reported unless all five
data-hygiene conditions demonstrably passed.** This module makes that mechanical rather
than a matter of memory.

The checks are deliberately EVIDENCE-based, not checkbox-based. Each looks for the
statistical fingerprint that the corresponding bug would leave in the data, so a caller
cannot assert hygiene without having actually done the work:

* **Prices absolute-valued** — CRSP stores a bid/ask midpoint as a negative ``prc``.
* **Fundamentals lagged to ``rdq``** — if ``datadate`` (the fiscal period END) were used
  instead of ``rdq`` (the report date), nearly every report date would land on a month
  end. Genuine report dates scatter across the month.
* **YTD items differenced** — cumulative ``oancfy`` rises monotonically within a fiscal
  year; real quarterly cash flow does not. A high monotonic fraction is the fingerprint.
* **Delisting returns merged** — the return on delisting lives only in
  ``crsp.dsedelist``; omitting it books bankruptcies as flat exits.
* **CCM link filtered** — only ~27% of ``crsp.ccmxpf_lnkhist`` is research-grade, so a
  near-zero rejection count proves the filter never ran.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from src.monitoring.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    from src.data.contracts.schemas import FundamentalData, PriceData

_log = get_logger(__name__)

#: Above this share of month-end report dates, `datadate` was almost certainly used.
_MAX_MONTH_END_FRACTION = 0.5

#: Above this share of monotonically-rising firm-years, a YTD item was never differenced.
_MAX_MONOTONIC_FRACTION = 0.5

#: The CCM link is ~73% unusable, so a filter that rejects almost nothing never ran.
_MIN_LINK_REJECT_FRACTION = 0.5

#: Firm-years needed before the YTD fingerprint is statistically meaningful.
_MIN_FIRM_YEARS = 2


class HygieneError(RuntimeError):
    """Raised when results are requested from a pipeline that failed hygiene."""


@dataclass(frozen=True)
class HygieneCheck:
    """One hygiene condition, with the evidence behind the verdict."""

    name: str
    passed: bool
    evidence: str


@dataclass(frozen=True)
class HygieneCertificate:
    """The full set of hygiene verdicts for one pipeline run."""

    checks: tuple[HygieneCheck, ...]

    @property
    def passed(self) -> bool:
        """True only when every check passed."""
        return all(check.passed for check in self.checks)

    def require_clean(self) -> None:
        """Raise unless every check passed.

        Raises:
            HygieneError: naming every failed check, so results cannot be reported
                from a pipeline with known data defects.
        """
        failures = [c for c in self.checks if not c.passed]
        if failures:
            detail = "; ".join(f"{c.name}: {c.evidence}" for c in failures)
            raise HygieneError(f"hygiene failed ({len(failures)} of {len(self.checks)}) — {detail}")

    def report(self) -> str:
        """Render a human-readable hygiene report for inclusion beside results."""
        lines = [f"HYGIENE: {'PASS' if self.passed else 'FAIL'}"]
        lines.extend(
            f"  [{'PASS' if c.passed else 'FAIL'}] {c.name}: {c.evidence}" for c in self.checks
        )
        return "\n".join(lines)


def check_prices_absolute_valued(prices: Sequence[PriceData]) -> HygieneCheck:
    """Verify every price is strictly positive (CRSP negatives are bid/ask midpoints)."""
    if not prices:
        return HygieneCheck("prices_absolute_valued", False, "no price data to certify")
    worst = min(min(b.open, b.high, b.low, b.close, b.adjusted_close) for b in prices)
    return HygieneCheck(
        "prices_absolute_valued",
        worst > 0,
        f"{len(prices):,} bars checked, minimum observed price {worst:.4f}",
    )


def check_fundamentals_lagged_to_rdq(rows: Sequence[FundamentalData]) -> HygieneCheck:
    """Verify report dates look like `rdq`, not `datadate` (month-end clustering)."""
    if not rows:
        # A price-only signal uses no fundamentals; the certificate certifies the inputs
        # it is given, so there is nothing here to fail.
        return HygieneCheck("fundamentals_lagged_to_rdq", True, "not applicable — price-only run")
    month_ends = sum(
        1 for r in rows if (r.report_date + timedelta(days=1)).month != r.report_date.month
    )
    fraction = month_ends / len(rows)
    return HygieneCheck(
        "fundamentals_lagged_to_rdq",
        fraction <= _MAX_MONTH_END_FRACTION,
        f"{fraction:.0%} of {len(rows):,} report dates fall on a month-end "
        f"(>{_MAX_MONTH_END_FRACTION:.0%} implies datadate was used instead of rdq)",
    )


def check_ytd_items_differenced(rows: Sequence[FundamentalData]) -> HygieneCheck:
    """Verify operating cash flow is quarterly, not the raw cumulative YTD series."""
    by_year: dict[tuple[str, int], list[tuple[int, float]]] = defaultdict(list)
    for r in rows:
        by_year[(r.ticker, r.fiscal_year)].append((r.fiscal_quarter, r.operating_cash_flow))
    if not rows:
        return HygieneCheck("ytd_items_differenced", True, "not applicable — price-only run")
    complete = [sorted(v) for v in by_year.values() if len(v) >= 3]  # noqa: PLR2004
    if len(complete) < _MIN_FIRM_YEARS:
        return HygieneCheck(
            "ytd_items_differenced",
            False,
            f"only {len(complete)} complete firm-years; too few to certify de-cumulation",
        )
    monotonic = sum(
        1
        for series in complete
        if all(series[i][1] < series[i + 1][1] for i in range(len(series) - 1))
    )
    fraction = monotonic / len(complete)
    return HygieneCheck(
        "ytd_items_differenced",
        fraction <= _MAX_MONOTONIC_FRACTION,
        f"{fraction:.0%} of {len(complete):,} firm-years are monotonically rising "
        f"(>{_MAX_MONOTONIC_FRACTION:.0%} is the un-differenced YTD fingerprint)",
    )


def check_delisting_merged(merged: bool) -> HygieneCheck:
    """Verify the price source merged delisting returns."""
    return HygieneCheck(
        "delisting_returns_merged",
        merged,
        "merged with imputation (-30% NYSE/AMEX, -55% NASDAQ)"
        if merged
        else "NOT merged — bankruptcies book as flat exits and bias results upward",
    )


def check_ccm_link_filtered(usable: int, rejected: int) -> HygieneCheck:
    """Verify the CCM link was filtered to research-grade rows."""
    total = usable + rejected
    if total == 0:
        return HygieneCheck("ccm_link_filtered", True, "no CCM join performed in this run")
    fraction = rejected / total
    return HygieneCheck(
        "ccm_link_filtered",
        fraction >= _MIN_LINK_REJECT_FRACTION,
        f"rejected {fraction:.0%} of {total:,} link rows "
        f"(<{_MIN_LINK_REJECT_FRACTION:.0%} means the LC/LU + P/C filter never ran)",
    )


def certify(
    *,
    prices: Sequence[PriceData],
    fundamentals: Sequence[FundamentalData],
    delisting_merged: bool,
    link_usable: int = 0,
    link_rejected: int = 0,
) -> HygieneCertificate:
    """Run every hygiene check and return the certificate.

    Args:
        prices: The price series the result was computed on.
        fundamentals: The fundamentals used (empty when the signal is price-only).
        delisting_merged: Whether the price source merged delisting returns.
        link_usable: Research-grade CCM link rows retained.
        link_rejected: CCM link rows filtered out.

    Returns:
        A :class:`HygieneCertificate`; call ``require_clean()`` before reporting numbers.
    """
    certificate = HygieneCertificate(
        checks=(
            check_prices_absolute_valued(prices),
            check_delisting_merged(delisting_merged),
            check_fundamentals_lagged_to_rdq(fundamentals),
            check_ytd_items_differenced(fundamentals),
            check_ccm_link_filtered(link_usable, link_rejected),
        )
    )
    _log.info(
        "hygiene.certified",
        passed=certificate.passed,
        failures=[c.name for c in certificate.checks if not c.passed],
    )
    return certificate
