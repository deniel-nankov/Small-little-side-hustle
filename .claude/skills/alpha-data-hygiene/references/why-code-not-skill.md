# Why the binary checks are not in this skill

A skill is *probabilistic*: it fires only when the model matches its description, and the
documented failure mode is an agent mid-tool-chain never reaching for it. A check with one
correct answer must not depend on that.

So the split is:

- **Code** (`src/utils/hygiene.py`, `src/data/wrds/delisting.py`, `src/data/wrds/ccm_link.py`)
  — the binary checks. `require_clean()` raises. CI runs them on every PR.
- **This skill** — the judgment: why the rule exists, when it applies, what to do at the
  boundary, and which hypotheses are worth pursuing at all.

Wrapping a deterministic test in prose adds an interpretation layer that only makes it
less reliable, and creates two sources of truth that eventually disagree.

**If a check ever passes in this skill's prose but fails in code, the code is right.**
Delete the prose version rather than reconciling them.

The hygiene checks are deliberately *evidence-based fingerprints*, not checkboxes — e.g.
month-end clustering of `report_date` betrays `datadate` used instead of `rdq`, and
monotonically-rising within-fiscal-year cash flow betrays an un-differenced YTD item. You
cannot assert hygiene without having done the work.
