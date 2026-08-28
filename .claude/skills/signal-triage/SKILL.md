---
name: signal-triage
description: >
  Decides whether a candidate trading signal is worth pursuing BEFORE any data work, and
  whether an already-tested signal should be kept or killed. Use when proposing a new
  signal or hypothesis; when asked "should I pursue / build / kill / prioritise this";
  when choosing between several ideas; or when a backtest result needs a keep-or-drop
  verdict. Applies the structural-edge test, the who-loses test, the crowding test, and
  the trial-count budget. Use it before writing code for a new signal, not after.
---

# Signal triage — is this worth pursuing?

A gate, not a scoring rubric. **Any single failure kills the hypothesis.** The purpose is
to spend the trial budget on ideas that could plausibly survive, because every test spent
raises the bar for everything that follows.

## Gate 1 — Who is on the other side, and why do they lose?

Name the counterparty and their motive. They must be **rationally willing** to accept a
worse price, not merely wrong. Examples that pass: a taxable investor harvesting a loss
worth more than the execution concession; a manager selling an embarrassing position
before a reporting date. Examples that fail: "the market underreacts", "investors are
irrational", "nobody has looked at this."

**If the counterparty cannot be named, stop here.** Do not proceed to data.

## Gate 2 — Is the edge structural or informational?

The edge must come from something institutional capital *cannot or will not* do: size,
mandate, index rules, tax treatment, or a lag that applies equally to everyone.

**The drop test:** would this signal work *better* for a firm with faster data or a bigger
research budget? If yes, **that is a reason to drop it, not to be excited.** We are not
competing on information.

## Gate 3 — Is it live-able?

Check `references/dataset-tiers.md` in the `alpha-data-hygiene` skill. If it needs Revere,
RavenPack, Panjiva, IBES, TAQ, OptionMetrics, or CRSP recency, it is a **paper, not a
strategy** — say so explicitly rather than building it quietly.

## Gate 4 — Is it already a known factor?

If the signal is a repackaging of market, size, value, profitability, investment, or
momentum, it will not survive the controls we run anyway. Say which factor it resembles
and why it is distinct — or drop it.

## Gate 5 — Does the arithmetic survive costs?

Rough it out before testing: expected turnover x 30 bps round trip against plausible
gross edge. A signal needing weekly rebalancing of illiquid small caps has to clear a very
high bar. If the arithmetic is implausible, say so now rather than after a backtest.

## Gate 6 — Trial budget

Check `docs/TRIAL_LOG.md`. Every test raises the multiple-testing discount on everything
that follows. Spending a trial on a weak idea is not free.

## If all six pass

Write the hypothesis down **before touching data**: economic rationale, counterparty,
universe, signal definition, formation and holding dates, falsification criteria. Then ask
before running it.

## Killing a tested signal

Kill it if the IC is indistinguishable from zero, if returns are concentrated in a few
periods or names, if it vanishes under factor controls, or if it goes negative net of
costs. **Great PnL with zero IC is a kill, not a keep** — that has now happened twice on
this project, and IC was the honest measure both times.
