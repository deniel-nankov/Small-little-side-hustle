---
name: alpha-data-hygiene
description: >
  Settled WRDS/CRSP/Compustat/IBES data-hygiene rules and overfitting discipline for this
  alpha-signal research repo. Use whenever building, reviewing, or backtesting a signal;
  pulling or joining WRDS data (CRSP, Compustat, IBES, 13F, short interest, Fama-French);
  computing returns; linking gvkey to permno; constructing a universe; or deciding whether
  a signal is worth pursuing. Also use when point-in-time, restatement, delisting returns,
  survivorship, look-ahead, holdout, factor controls, turnover, capacity, cost drag, or
  trial count come up — even if the phrase "data hygiene" is never said. These rules are
  SETTLED and empirically verified: apply them, do not re-derive or re-litigate them.
---

# Alpha data hygiene & overfitting discipline

These rules were established empirically against live WRDS data and are **settled facts**.
Do not re-derive them, and do not spend the user's time re-verifying them.

## Before any data work

1. The hypothesis needs a **written economic rationale first** — including *who is on the
   other side of the trade and why they are willing to lose*. If that question cannot be
   answered, the hypothesis is skipped rather than tested.
2. **One hypothesis at a time.**
3. Increment and report the **trial count** (`docs/TRIAL_LOG.md`). It determines how much
   to discount whatever survives.
4. **Never look at the 2021–2024 holdout without asking first.** Say out loud each time
   you are tempted. It is a *weak* holdout because the data is stale — surviving it is
   necessary, not sufficient.

## Hard scope constraints

- **CRSP ends 2024-12-31.** Nothing can be validated on 2025 or 2026 using CRSP returns.
  Say so out loud if ever tempted to try.
- **Live-able data only** for anything called a strategy: CRSP/Polygon prices, EDGAR
  fundamentals, FINRA short interest, 13F (with its permanent 45-day statutory lag).
  If a signal needs anything else, **stop and say so instead of building it**.
- Universe: small cap ~$300M–$2B (CRSP size deciles ~6–8), US common (`shrcd` 10/11).
- Horizon 1 week to 3 months, cross-sectional, long/short.
- **Costs: 30 bps round trip, stated in every result.**

## The edge must be structural, not informational

Look for edges that institutional capital *cannot or will not* take: size, mandate, index
rules, tax treatment, or a lag that applies equally to everyone. **If a signal would
obviously work better for a firm with faster data, that is a reason to drop it, not a
reason to be excited.**

## Dataset traps — load only the reference for the dataset in play

| Dataset | Reference |
|---|---|
| CRSP prices, returns, delisting, survivorship | `references/crsp.md` |
| Compustat restatement and point-in-time | `references/compustat.md` |
| IBES adjusted vs unadjusted | `references/ibes.md` |
| CRSP/Compustat linking | `references/ccm.md` |
| What is live-able vs research-only | `references/dataset-tiers.md` |
| What every signal must report | `references/signal-checklist.md` |

## Deterministic checks live in CODE, not in this skill

This skill carries the **why** and the **when**. The binary checks are enforced by
`src/utils/hygiene.py` and refuse to be skipped:

```python
from src.utils.hygiene import certify
cert = certify(prices=..., fundamentals=..., delisting_merged=True,
               link_usable=..., link_rejected=...)
cert.require_clean()   # raises HygieneError naming every failure
print(cert.report())   # the block that must accompany any performance number
```

**No performance number is reported until that certificate passes.** If a check ever
passes here in prose but fails in code, the code is right — see
`references/why-code-not-skill.md`.
