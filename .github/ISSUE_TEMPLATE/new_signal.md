---
name: New signal proposal
about: Propose a new alpha signal
title: "[signal] "
labels: ["signal", "P2-medium"]
---

## Signal proposal

**Signal name:** (short, snake_case)
**Category:** (momentum / value / quality / earnings / ownership / supply_chain / other)
**Hypothesis:** (plain English — why should this predict future returns?)
**Economic intuition:** (what market behavior or anomaly does this exploit?)
**Data sources needed:** (which FactSet datasets?)
**Expected holding period:** (days)
**Expected IC:** (your estimate)
**Similar known signals:** (overlap with Alpha101 or anything in the registry?)
**Point-in-time confirmed:** (yes/no — is the data look-ahead safe?)

## Checklist before opening the PR
- [ ] Unit tests written (`tests/unit/test_<name>.py`)
- [ ] Passes all 7 validation tests
- [ ] Added to signal registry with status `VALIDATED`
- [ ] Docstring explaining the signal formula
