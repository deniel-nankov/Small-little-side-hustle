# CRSP/Compustat link traps (settled, verified live)

`crsp.ccmxpf_lnkhist` is **73% unusable**. Measured: 123,388 rows → 33,324 usable,
90,064 rejected.

- **Keep only `linktype` in {LC, LU}.** NR (46,853) and NU (34,014) are unresearched;
  LX/LD/LN/LS/NP are structural variants. Together they are ~73% of the table.
- **Keep only `linkprim` in {P, C}.** N and J are secondary/joiner rows that duplicate a
  company and silently double-weight it in a cross-section.
- **Respect `linkdt` and `linkenddt`, inclusively.** Ignoring the window attaches a
  company's financials to a security in periods when the link was not valid — post-merger
  figures landing on a pre-merger stub.
- **A null `linkenddt` means still open** (26,386 links), not invalid.
- Unusable link types frequently carry a null `lpermno`; reject those rows outright.

Enforced by `src/data/wrds/ccm_link.py`. Sanity check: permno 14593 resolves to gvkey
001690 in 2020 and to **nothing** in 1975 (pre-IPO).
