"""Unit tests for the hygiene certificate that gates every reported result.

The rule: no performance number is reported unless all five conditions demonstrably
passed. These checks are deliberately EVIDENCE-based rather than checkbox-based — each
looks for the statistical fingerprint the corresponding bug would leave behind, so
asserting hygiene without doing the work fails.
"""

from __future__ import annotations

from datetime import date

import pytest
from src.data.contracts.schemas import DataSourceName, FundamentalData, PriceData
from src.utils.hygiene import (
    HygieneError,
    certify,
    check_ccm_link_filtered,
    check_fundamentals_lagged_to_rdq,
    check_prices_absolute_valued,
    check_ytd_items_differenced,
)


def _bar(day: date, close: float, volume: float = 1000.0) -> PriceData:
    return PriceData(
        ticker="AAPL",
        date=day,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=volume,
        adjusted_close=close,
        data_source=DataSourceName.crsp,
        point_in_time=True,
    )


def _fund(report_date: str, fy: int, fq: int, ocf: float) -> FundamentalData:
    return FundamentalData(
        ticker="AAPL",
        report_date=date.fromisoformat(report_date),
        fiscal_year=fy,
        fiscal_quarter=fq,
        total_assets=1000.0,
        net_income=50.0,
        operating_cash_flow=ocf,
        revenue=500.0,
        is_point_in_time=True,
    )


# ------------------------------------------------------------ prices absolute-valued


def test_positive_prices_pass() -> None:
    check = check_prices_absolute_valued([_bar(date(2020, 1, 2), 50.0)])
    assert check.passed is True
    assert "1" in check.evidence


def test_empty_price_set_fails_rather_than_vacuously_passing() -> None:
    assert check_prices_absolute_valued([]).passed is False


# ------------------------------------------------- fundamentals lagged to rdq
# If someone used `datadate` (the fiscal period END) instead of `rdq` (the REPORT date),
# nearly every report_date lands on a month end. Real rdq dates scatter across the month.


def test_report_dates_that_scatter_pass() -> None:
    rows = [
        _fund("2020-01-28", 2020, 1, 10.0),
        _fund("2020-04-30", 2020, 2, 12.0),
        _fund("2020-07-14", 2020, 3, 11.0),
        _fund("2020-10-09", 2020, 4, 13.0),
    ]
    assert check_fundamentals_lagged_to_rdq(rows).passed is True


def test_month_end_clustering_is_caught_as_datadate_misuse() -> None:
    rows = [
        _fund("2020-03-31", 2020, 1, 10.0),
        _fund("2020-06-30", 2020, 2, 12.0),
        _fund("2020-09-30", 2020, 3, 11.0),
        _fund("2020-12-31", 2020, 4, 13.0),
    ]
    check = check_fundamentals_lagged_to_rdq(rows)
    assert check.passed is False
    assert "month-end" in check.evidence


# ------------------------------------------------------------- YTD items differenced
# Cumulative oancfy rises monotonically within a fiscal year. Genuine quarterly cash flow
# does not. A high monotonic fraction is the fingerprint of the un-differenced bug.


def test_realistic_quarterly_cash_flow_passes() -> None:
    rows = [
        _fund("2020-01-28", 2020, 1, 8140.0),
        _fund("2020-04-28", 2020, 2, 2066.0),  # Oracle's real de-cumulated quarters
        _fund("2020-07-28", 2020, 3, 7151.0),
        _fund("2020-10-28", 2020, 4, 14620.0),
        _fund("2021-01-28", 2021, 1, 9000.0),
        _fund("2021-04-28", 2021, 2, 3000.0),
        _fund("2021-07-28", 2021, 3, 8000.0),
        _fund("2021-10-28", 2021, 4, 5000.0),
    ]
    assert check_ytd_items_differenced(rows).passed is True


def test_cumulative_cash_flow_is_caught() -> None:
    rows = [
        _fund("2020-01-28", 2020, 1, 8140.0),
        _fund("2020-04-28", 2020, 2, 10206.0),  # the raw YTD series, never differenced
        _fund("2020-07-28", 2020, 3, 17357.0),
        _fund("2020-10-28", 2020, 4, 31977.0),
        _fund("2021-01-28", 2021, 1, 9000.0),
        _fund("2021-04-28", 2021, 2, 15000.0),
        _fund("2021-07-28", 2021, 3, 22000.0),
        _fund("2021-10-28", 2021, 4, 30000.0),
    ]
    check = check_ytd_items_differenced(rows)
    assert check.passed is False
    assert "monoton" in check.evidence


# ------------------------------------------------------------------ CCM link filtered


def test_link_filter_passes_at_the_expected_fraction() -> None:
    assert check_ccm_link_filtered(usable=33324, rejected=90064).passed is True


def test_unfiltered_link_is_caught() -> None:
    # Keeping ~everything means the filter was never applied.
    check = check_ccm_link_filtered(usable=123388, rejected=0)
    assert check.passed is False
    assert "filter" in check.evidence.lower()


# --------------------------------------------------------------------- certification


def _clean_inputs() -> dict:
    return {
        "prices": [_bar(date(2020, 1, 2), 50.0), _bar(date(2020, 1, 3), 51.0)],
        "fundamentals": [
            _fund("2020-01-28", 2020, 1, 8140.0),
            _fund("2020-04-28", 2020, 2, 2066.0),
            _fund("2020-07-14", 2020, 3, 7151.0),
            _fund("2020-10-09", 2020, 4, 14620.0),
            _fund("2021-01-28", 2021, 1, 9000.0),
            _fund("2021-04-28", 2021, 2, 3000.0),
            _fund("2021-07-14", 2021, 3, 8000.0),
            _fund("2021-10-09", 2021, 4, 5000.0),
        ],
        "delisting_merged": True,
        "link_usable": 33324,
        "link_rejected": 90064,
    }


def test_clean_pipeline_certifies() -> None:
    cert = certify(**_clean_inputs())
    assert cert.passed is True
    assert len(cert.checks) == 5
    cert.require_clean()  # must not raise


def test_unmerged_delisting_fails_certification() -> None:
    cert = certify(**{**_clean_inputs(), "delisting_merged": False})
    assert cert.passed is False
    assert any("delisting" in c.name for c in cert.checks if not c.passed)


def test_require_clean_raises_and_names_every_failure() -> None:
    cert = certify(**{**_clean_inputs(), "delisting_merged": False, "link_rejected": 0})
    with pytest.raises(HygieneError) as excinfo:
        cert.require_clean()
    message = str(excinfo.value)
    assert "delisting" in message
    assert "ccm" in message


def test_certificate_renders_a_readable_report() -> None:
    report = certify(**_clean_inputs()).report()
    assert "PASS" in report
    for name in ("delisting", "ccm", "rdq", "ytd", "price"):
        assert name in report.lower()


def test_price_only_run_is_not_penalised_for_having_no_fundamentals() -> None:
    # The tax-loss hypothesis is price-only; a certificate must not fail it for the
    # absence of data it legitimately never used.
    cert = certify(
        prices=[_bar(date(2020, 1, 2), 50.0)],
        fundamentals=[],
        delisting_merged=True,
        link_usable=0,
        link_rejected=0,
    )
    assert cert.passed is True
    assert "not applicable" in cert.report()
