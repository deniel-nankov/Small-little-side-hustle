"""Unit tests for the WRDS-backed DataSource — CRSP prices (#55).

Every behavior pinned here was observed on the LIVE data and would silently corrupt a
backtest if mishandled:

* **Ticker reuse**: 8,391 tickers map to more than one ``permno`` over time, so the
  ticker→permno mapping MUST be date-aware or a backtest silently mixes two companies.
* **Negative prices**: CRSP stores a bid/ask midpoint as a NEGATIVE ``prc`` when no
  trade occurred (23 such rows for Oracle alone). ``abs()`` is mandatory.
* **Null OHLC**: 1,588 Oracle rows have no ``openprc``; ``askhi``/``bidlo`` can be null.
* **Total return**: dividends live in ``ret``, not in ``prc``. ``adjusted_close`` is
  built by compounding ``ret`` so pct-change of it equals CRSP's own total return.
"""

from __future__ import annotations

from datetime import date

import pytest
from src.data.contracts.schemas import DataSourceName
from src.data.wrds.source import WRDSSource

# permno 10104 = ORACLE; 11850 is a fabricated reuse of the same ticker in a later era.
_STOCKNAMES = [
    {
        "permno": 10104,
        "ticker": "ORCL",
        "comnam": "ORACLE CORP",
        "namedt": "1995-06-01",
        "nameenddt": "2024-12-31",
        "ncusip": "68389X10",
        "cusip": "68389X10",
    },
    {
        "permno": 99999,
        "ticker": "ORCL",
        "comnam": "OLD ORACLE SYSTEMS",
        "namedt": "1986-03-12",
        "nameenddt": "1995-05-31",
        "ncusip": "68389X10",
        "cusip": "68389X10",
    },
    {
        "permno": 14593,
        "ticker": "AAPL",
        "comnam": "APPLE INC",
        "namedt": "1980-12-12",
        "nameenddt": "2024-12-31",
        "ncusip": "03783310",
        "cusip": "03783310",
    },
]


def _bar(day: str, prc: float, ret: float | None = 0.01, **kw: object) -> dict:
    return {
        "permno": 10104,
        "date": day,
        "prc": prc,
        "openprc": kw.get("openprc", abs(prc) - 1),
        "askhi": kw.get("askhi", abs(prc) + 1),
        "bidlo": kw.get("bidlo", abs(prc) - 2),
        "vol": kw.get("vol", 1000.0),
        "ret": ret,
        "cfacpr": kw.get("cfacpr", 1.0),
    }


class _FakeClient:
    """Stands in for WRDSClient, recording calls and serving canned tables."""

    def __init__(self, tables: dict[str, list[dict]]) -> None:
        self.tables = tables
        self.calls: list[tuple[str, dict]] = []

    def get_rows(self, table, *, filters=None, ordering=None, max_rows=None):  # noqa: ANN001, ANN201, ARG002
        self.calls.append((table, dict(filters or {})))
        rows = self.tables.get(table, [])
        for key, want in (filters or {}).items():
            rows = [r for r in rows if str(r.get(key)) == str(want)]
        return rows


def _source(bars: list[dict] | None = None) -> tuple[WRDSSource, _FakeClient]:
    client = _FakeClient(
        {"crsp.stocknames": _STOCKNAMES, "crsp.dsf": bars if bars is not None else []}
    )
    return WRDSSource(client), client  # type: ignore[arg-type]


# ------------------------------------------------------------- identifier resolution


def test_ticker_resolves_to_permno_valid_on_that_date() -> None:
    src, _ = _source()
    assert src.permno_for("ORCL", date(2020, 1, 2)) == 10104
    assert src.permno_for("ORCL", date(1990, 1, 2)) == 99999  # the earlier company!


def test_unknown_ticker_resolves_to_none() -> None:
    src, _ = _source()
    assert src.permno_for("NOPE", date(2020, 1, 2)) is None


def test_date_outside_every_name_window_resolves_to_none() -> None:
    src, _ = _source()
    assert src.permno_for("ORCL", date(1970, 1, 2)) is None


def test_company_that_died_mid_window_still_resolves() -> None:
    # THE survivorship case: Lehman delisted Sept 2008. Resolving at the window END
    # (2008-12-31) finds nothing, which would silently drop every bankrupt company —
    # exactly the bias CRSP exists to eliminate. Resolution must consider overlap.
    src, _ = _source()
    src._names = [  # noqa: SLF001
        {
            "permno": 84129,
            "ticker": "LEH",
            "comnam": "LEHMAN BROTHERS HOLDINGS INC",
            "namedt": "1994-05-04",
            "nameenddt": "2008-09-16",
            "ncusip": "52490810",
            "cusip": "52490810",
        }
    ]
    assert src.permno_in_window("LEH", date(2008, 1, 1), date(2008, 12, 31)) == 84129
    assert src.permno_for("LEH", date(2008, 12, 31)) is None  # point lookup still exact


def test_window_resolution_prefers_the_longest_overlap() -> None:
    # When a ticker is recycled inside the window, take the company that held it longest.
    src, _ = _source()
    assert src.permno_in_window("ORCL", date(1994, 1, 1), date(2020, 1, 1)) == 10104


def test_window_resolution_returns_none_when_no_overlap() -> None:
    src, _ = _source()
    assert src.permno_in_window("ORCL", date(1970, 1, 1), date(1975, 1, 1)) is None


def test_stocknames_is_fetched_once_and_cached() -> None:
    src, client = _source()
    src.permno_for("ORCL", date(2020, 1, 2))
    src.permno_for("AAPL", date(2020, 1, 2))
    assert sum(1 for t, _ in client.calls if t == "crsp.stocknames") == 1


# --------------------------------------------------------------------- price mapping


def test_negative_price_is_absolute_valued() -> None:
    # CRSP encodes "no trade; this is a bid/ask midpoint" as a NEGATIVE prc.
    src, _ = _source([_bar("2020-01-02", -50.0, ret=None)])
    bars = src.get_prices(["ORCL"], date(2020, 1, 1), date(2020, 1, 31))
    assert bars[0].close == 50.0
    assert bars[0].data_source is DataSourceName.crsp


def test_null_open_high_low_are_filled_consistently() -> None:
    src, _ = _source([_bar("2020-01-02", 50.0, openprc=None, askhi=None, bidlo=None)])
    bar = src.get_prices(["ORCL"], date(2020, 1, 1), date(2020, 1, 31))[0]
    assert bar.open == bar.close == 50.0
    assert bar.low <= bar.close <= bar.high  # contract validator must be satisfiable


def test_ohlc_is_clamped_so_the_contract_never_rejects_a_row() -> None:
    # A stale askhi below the close would otherwise fail PriceData's validator.
    src, _ = _source([_bar("2020-01-02", 50.0, askhi=10.0, bidlo=99.0)])
    bar = src.get_prices(["ORCL"], date(2020, 1, 1), date(2020, 1, 31))[0]
    assert bar.low <= bar.open <= bar.high
    assert bar.low <= bar.close <= bar.high


def test_dates_are_sliced_to_the_requested_window() -> None:
    bars = [_bar("2019-12-31", 40.0), _bar("2020-01-02", 50.0), _bar("2020-02-05", 60.0)]
    src, _ = _source(bars)
    got = src.get_prices(["ORCL"], date(2020, 1, 1), date(2020, 1, 31))
    assert [b.date for b in got] == [date(2020, 1, 2)]


def test_rows_without_a_price_are_skipped() -> None:
    src, _ = _source([_bar("2020-01-02", 50.0), {**_bar("2020-01-03", 1.0), "prc": None}])
    assert len(src.get_prices(["ORCL"], date(2020, 1, 1), date(2020, 1, 31))) == 1


def test_end_before_start_raises() -> None:
    src, _ = _source()
    with pytest.raises(ValueError, match="precedes"):
        src.get_prices(["ORCL"], date(2020, 2, 1), date(2020, 1, 1))


def test_unknown_ticker_is_skipped_not_fatal() -> None:
    src, _ = _source([_bar("2020-01-02", 50.0)])
    got = src.get_prices(["NOPE", "ORCL"], date(2020, 1, 1), date(2020, 1, 31))
    assert {b.ticker for b in got} == {"ORCL"}


# ------------------------------------------------- total-return adjusted close (divs)


def test_adjusted_close_compounds_crsp_total_return() -> None:
    # Dividends live in `ret`, never in `prc`. Pct-change of adjusted_close must equal
    # CRSP's own total return, and the series is anchored to the final actual close.
    bars = [
        _bar("2020-01-02", 100.0, ret=None),
        _bar("2020-01-03", 100.0, ret=0.10),  # flat price, +10% total return = dividend
    ]
    src, _ = _source(bars)
    got = src.get_prices(["ORCL"], date(2020, 1, 1), date(2020, 1, 31))
    assert got[-1].adjusted_close == pytest.approx(100.0)  # anchored to last close
    realized = got[-1].adjusted_close / got[0].adjusted_close - 1.0
    assert realized == pytest.approx(0.10)  # the dividend is captured
    assert got[0].close == got[1].close  # ...and the raw price never moved


def test_adjusted_close_is_positive_even_with_negative_returns() -> None:
    bars = [_bar("2020-01-02", 100.0, ret=None), _bar("2020-01-03", 60.0, ret=-0.40)]
    src, _ = _source(bars)
    got = src.get_prices(["ORCL"], date(2020, 1, 1), date(2020, 1, 31))
    assert all(b.adjusted_close > 0 for b in got)


def test_point_in_time_flag_is_set() -> None:
    src, _ = _source([_bar("2020-01-02", 50.0)])
    assert src.get_prices(["ORCL"], date(2020, 1, 1), date(2020, 1, 31))[0].point_in_time is True


# ------------------------------------------------------------------ unimplemented yet


@pytest.mark.parametrize("method", ["get_estimates", "get_fundamentals", "get_ownership"])
def test_pending_endpoints_raise_not_implemented(method: str) -> None:
    src, _ = _source()
    with pytest.raises(NotImplementedError):
        getattr(src, method)(["ORCL"], date(2020, 1, 1), date(2020, 1, 31))


def test_supply_chain_not_implemented_yet() -> None:
    src, _ = _source()
    with pytest.raises(NotImplementedError):
        src.get_supply_chain(["ORCL"])


def test_factory_returns_wrds_source_when_configured() -> None:
    from config.settings import DataSourceKind, Settings
    from src.data.source import get_data_source

    cfg = Settings(data_source=DataSourceKind.wrds, wrds_api_token="tok")  # noqa: S106
    assert isinstance(get_data_source(cfg), WRDSSource)


def test_wrds_profile_requires_a_token() -> None:
    from config.settings import DataSourceKind, MissingCredentialError, Settings

    cfg = Settings(data_source=DataSourceKind.wrds, wrds_api_token=None)
    assert cfg.required_for_runtime() == ["wrds_api_token"]
    with pytest.raises(MissingCredentialError, match="wrds_api_token"):
        cfg.validate_for_runtime()
