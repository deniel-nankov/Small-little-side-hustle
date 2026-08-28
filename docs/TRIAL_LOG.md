# Trial log

Every hypothesis tested against data, in order. The count determines how much to discount
whatever eventually survives — a signal that looks good after twenty trials is far weaker
evidence than the same signal after two.

**Current trial count: 2** (one void).

| # | Hypothesis | Window | Verdict | Notes |
|---|---|---|---|---|
| 1 | Fundamental composite (accruals + ROA + revenue acceleration), 200 US large caps | 2024-07 → 2026-06, train/test w/ 30d embargo | **FAIL** | TRAIN IC +0.0013 (p=0.95). TEST: +21.8% ann., Sharpe 1.91, maxDD −3.1% — but **IC −0.033**. Great PnL, no predictive power. Also pre-dates the hygiene layer. |
| 2 | TrueBeats (accuracy-weighted analyst revisions), 45 large caps | 2018–2024, train/test w/ 30d embargo | **VOID** | Failed both windows, but the analyst-accuracy input was contaminated by issue #66 (adjusted estimates paired with unadjusted actuals = a 40x split factor). Verdict is not trustworthy either way. Also IBES = research-only, so out of scope regardless. |

## Pre-registered, not yet run

**Hypothesis 3 — turn-of-year tax-loss and window-dressing reversal in small caps.**
Counterparties: taxable investors buying a tax deduction worth more than the execution
concession, and managers selling losers before year-end reports. Structural, not
informational — the trigger is the tax and reporting calendar, so faster data does not
help. Universe: CRSP deciles 6–8, `shrcd` 10/11, price > $5. Signal: trailing Jan 1 →
Nov 30 return, long bottom quintile / short top. Form Nov 30, hold to Feb 28. Prices only
(Polygon-replicable). Costs 30 bps round trip. Train 1990–2020 (~31 annual observations).
**Holdout 2021–2024 untouched.** Known weakness stated up front: one observation per year
is thin statistical power.
