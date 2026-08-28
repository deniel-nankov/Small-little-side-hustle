# Compustat traps (settled, verified live)

- **Compustat is restated. There is no point-in-time table in `comp.*`** — verified, zero
  such tables. The standard files overwrite history.
- **The only honest as-of date is `rdq`** (the date the company reported), never
  `datadate` (the fiscal period end). Using `datadate` leaks roughly ten days of hindsight
  into every observation.
- **`compsnap`** (124 tables) is the Compustat Snapshot point-in-time product. Prefer it
  where true unrestated history matters.
- **Year-to-date items reset annually and must be differenced.** `oancfy` is cumulative
  within the fiscal year — Oracle FY2025 runs 8,140 → 10,206 → 17,357 → 31,977, then
  resets. Reading it as quarterly overstates Q4 cash flow by roughly 2x and wrecks any
  accruals signal. Quarterly figure = difference against the prior quarter **of the same
  fiscal year**; Q1 is the raw value.
- Apply the standard academic screen — `datafmt=STD`, `indfmt=INDL`, `consol=C`,
  `popsrc=D` — or restated/summary rows double-count a period.
- Rows with a null `rdq` have no point-in-time meaning and must be dropped.
