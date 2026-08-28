# IBES traps (settled, verified live)

- **Standard IBES files are retroactively restated for splits.** Verified: 261 of 327 NVDA
  consensus rows differ by >50% between the original and current files. On 2024-03-14
  NVDA's FY2025 consensus was **published at $24.50**; the standard file now shows
  **$2.45**, restated for a June 2024 split that was unknowable at the time. Using the
  adjusted file is look-ahead.
- **Use `detu_epsus` and `actu_epsus` only — both unadjusted.** They share the
  originally-published scale.
- **NEVER pair an adjusted file with an unadjusted one.** This was a real shipped bug
  (issue #66): `det_epsus` (adjusted) paired with `actu_epsus` (unadjusted) gave NVDA
  FY2020 estimates of $0.03–$0.37 against an actual of **$5.79** — a 40x split factor.
  Any error computed across that gap measures the split, not skill, and when the offset
  swamps the cross-sectional spread the accuracy ranking **inverts**, ordering analysts by
  who forecast the largest number.
- Unadjusted data produces **spurious revisions across a split date** (NVDA 2024:
  $4.39 → $2.93 looks like −33% but is really +6.7x). A revision signal must normalise
  using point-in-time adjustment factors from `ibes.adj` / `ibes.adjsum` — splits known
  **as of the estimate date**, never today's cumulative factor.
- Point-in-time dates: `anndats` for estimates and for actuals. Rows with a null `anndats`
  cannot be used point-in-time and must be dropped.
- **IBES is research-only.** Anything built on it is a paper, not a strategy.
