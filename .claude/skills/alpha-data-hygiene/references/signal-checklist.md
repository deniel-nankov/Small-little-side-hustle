# What every signal must report

No performance number appears until `src/utils/hygiene.py::certify(...).require_clean()`
passes. Print `cert.report()` beside the results.

Then report, without exception:

1. **Information coefficient and its decay** — the honest measure. Two prior experiments
   both showed PnL and IC pointing in opposite directions, and IC was right both times.
   A strategy with great PnL and zero IC is luck that has not finished happening.
2. **Turnover implied** by the rebalance rule.
3. **Concentration** — across time (is it one good year?) and across names (is it three
   stocks?).
4. **Net of the stated cost assumption** (30 bps round trip), stated explicitly.
5. **Factor controls** — market, size, value, profitability, investment, momentum.
   If the signal disappears under them, **say so plainly**.
6. **Capacity in dollars.** A signal that only works below deployable size is useful
   information, not a failure.
7. **The current trial count**, so the reader can discount appropriately.

Never scan variables looking for what fits.
