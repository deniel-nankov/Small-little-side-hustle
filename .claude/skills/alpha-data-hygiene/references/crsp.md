# CRSP traps (settled, verified live)

- **Coverage ends 2024-12-31.** ~20 months stale as of Aug 2026. Nothing validates on
  2025/2026 with CRSP returns.
- **Negative `prc` is a bid/ask midpoint**, not a price — CRSP's way of saying "no trade
  occurred". Take `abs()`; the sign is a quality flag, not data.
- **Dividends live in `ret`, never in `prc`.** Build an adjusted series by compounding
  `ret`; use `cfacpr` for splits. A price-only return series silently drops dividends.
- **Ticker reuse: 8,391 tickers map to more than one `permno`.** `permno` is the only
  stable identifier. Resolve tickers **by window overlap, not at a point in time** —
  resolving at the window end silently drops every company that died inside the window
  (Lehman returned nothing for a 2008 backtest), which is precisely the survivorship bias
  CRSP exists to remove. Lehman is permno **80599**.
- **Delisting returns are in a separate file** (`crsp.dsedelist`), never in `crsp.dsf`.
  Reading the daily file alone books every bankruptcy as a flat exit at the last quote.
  Measured: 22,124 delisting events sampled, **13.4% carry no `dlret` at all**.
  Impute the missing ones at **−30% NYSE/AMEX, −55% NASDAQ**, and only for
  performance-related codes (400s liquidation, 500s dropped-for-cause). Mergers (200s)
  are exits at fair value and must never be imputed as distress.
  Enforced by `src/data/wrds/delisting.py`, on by default.
- Universe construction, not CRSP, is where survivorship bias enters: 38,872 permnos ever
  existed, 26,767 are US common stock. Picking today's ticker list reintroduces the bias.
