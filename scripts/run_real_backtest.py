"""CLI: backtest the fundamental-factor signal on the configured data source.

The first real-data run of the platform. Uses the DataSource selected by ``DATA_SOURCE``
(``public`` = free Yahoo prices + EDGAR point-in-time fundamentals), wrapped in the PIT
leakage guard, through the full 7-test validation suite. Run e.g.:

    DATA_SOURCE=public PYTHONPATH=. python scripts/run_real_backtest.py --end 2026-06-30

Exit code 0 means the pipeline ran (a failed validation is a valid research outcome and
is reported in the summary); non-zero means the pipeline itself errored.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from config.settings import get_settings
from src.data.contracts.schemas import BacktestResult
from src.data.public.edgar import EdgarClient
from src.data.source import get_data_source
from src.monitoring.audit import AuditLog
from src.pipeline.real_backtest import run_fundamental_backtest, run_train_test_backtest
from src.signals.validation.splits import DEFAULT_EMBARGO_DAYS, make_train_test_split

#: Liquid, non-financial US large caps (financials report revenue under different XBRL
#: concepts and would be skipped by the EDGAR parser's four-concept join).
DEFAULT_UNIVERSE = (
    "AAPL,MSFT,NVDA,GOOGL,AMZN,META,TSLA,AVGO,ORCL,CRM,"
    "ADBE,AMD,QCOM,TXN,CSCO,IBM,INTC,NKE,MCD,HD,"
    "PG,KO,PEP,WMT,COST,JNJ,LLY,MRK,TMO,CAT"
)


def _write_summary(result: BacktestResult, label: str) -> None:
    """Write one window's PnL-style summary to stdout."""
    verdict = "PASSED" if result.passed_validation else "FAILED"
    sys.stdout.write(
        f"\n=== {label}: {result.signal_name} "
        f"({result.start_date} .. {result.end_date}) ===\n"
        f"verdict:            {verdict}\n"
        f"mean IC:            {result.mean_ic:+.4f}\n"
        f"ICIR:               {result.icir:+.2f}\n"
        f"t-stat / p-value:   {result.t_statistic:+.2f} / {result.p_value:.4f}\n"
        f"positive-IC days:   {result.positive_ic_ratio:.1%}\n"
        f"ann. return (L/S):  {result.annualized_return:+.2%}\n"
        f"Sharpe:             {result.sharpe_ratio:+.2f}\n"
        f"max drawdown:       {result.max_drawdown:.2%}\n"
        f"regimes:            {result.regime_results}\n"
    )
    if result.failure_reasons:
        sys.stdout.write("failure reasons:\n")
        for reason in result.failure_reasons:
            sys.stdout.write(f"  - {reason}\n")


def main(argv: list[str] | None = None) -> int:
    """Parse args, run the backtest pipeline, and write a summary. Returns exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", default=DEFAULT_UNIVERSE, help="comma-separated universe")
    parser.add_argument(
        "--universe-top",
        type=int,
        default=0,
        metavar="N",
        help="use the top-N companies from SEC's listing instead of --tickers "
        "(TODAY'S list — historical runs carry survivorship bias)",
    )
    parser.add_argument("--start", type=date.fromisoformat, default=date(2024, 7, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2026, 6, 30))
    parser.add_argument("--score-every", type=int, default=5, help="score every Nth trading day")
    parser.add_argument("--n-trials", type=int, default=1, help="candidate signals tried")
    parser.add_argument(
        "--oos",
        type=float,
        default=0.0,
        metavar="FRACTION",
        help="enable train/test discipline: fraction of the span held out as test (e.g. 0.3)",
    )
    parser.add_argument("--embargo-days", type=int, default=DEFAULT_EMBARGO_DAYS)
    parser.add_argument("--out", type=Path, default=Path("data/backtests"))
    parser.add_argument("--audit", type=Path, default=Path("data/audit/backtests.jsonl"))
    args = parser.parse_args(argv)

    cfg = get_settings()
    source = get_data_source(cfg)
    if args.universe_top > 0:
        tickers = EdgarClient(cfg.edgar_user_agent).top_tickers(args.universe_top)
        sys.stdout.write(
            f"universe: top {len(tickers)} from SEC listing "
            "(today's list — survivorship-biased for historical windows)\n"
        )
    else:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    audit = AuditLog(args.audit)

    if args.oos > 0:
        split = make_train_test_split(
            args.start, args.end, test_fraction=args.oos, embargo_days=args.embargo_days
        )
        train_result, test_result = run_train_test_backtest(
            source,
            tickers,
            split,
            score_every=args.score_every,
            n_trials=args.n_trials,
            audit=audit,
            out_dir=args.out,
        )
        _write_summary(train_result, f"TRAIN (in-sample) on {source.name}")
        _write_summary(test_result, f"TEST (out-of-sample, embargo {split.embargo_days}d)")
    else:
        result = run_fundamental_backtest(
            source,
            tickers,
            args.start,
            args.end,
            score_every=args.score_every,
            n_trials=args.n_trials,
            audit=audit,
            out_dir=args.out,
        )
        _write_summary(result, f"{source.name}")

    sys.stdout.write(f"\naudit chain intact:  {audit.verify()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
