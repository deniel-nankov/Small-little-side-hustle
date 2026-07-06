# HANDOFF — yale-alpha-fund (project state & onboarding)

**Purpose:** single source of truth so a fresh chat (or a new engineer) can pick up
instantly without re-deriving everything. If you're an AI assistant starting cold: read
this top-to-bottom first, then `docs/ARCHITECTURE.md` and `docs/PRINCIPLES.md`.

> **Paste-into-a-new-chat bootstrap:**
> *"I'm continuing work on the `yale-alpha-fund` repo at `~/Documents/yale-alpha-fund`. Read
> `HANDOFF.md` at the repo root for full context (structure, status, workflow, blockers),
> then confirm you're oriented before doing anything."*

Last updated: 2026-07-05.

---

## 1. What this is

An **institutional-grade algorithmic trading research platform** for a Yale hedge-fund club.
Pulls institutional data → AI/hand-built signal discovery → rigorous validation → portfolio
construction → (eventually) execution. Built structure-first: everything typed, tested,
documented, reversible. Real money is far downstream and heavily gated.

**Six layers** (data flows downward only):
`data → signals(construction/discovery) → validation → combination → portfolio → execution`
Monitoring is horizontal (logging + audit); nothing depends on it except to import the
logger/audit.

**Current reality:** the entire pipeline runs **end-to-end on synthetic fixture data** —
signals, the 7-test validation suite, mean-CVaR portfolio, the whole loop. Real data
(FactSet) is blocked on a licensing entitlement (see §9), NOT on code.

---

## 2. Quick start / how to run it

```bash
cd ~/Documents/yale-alpha-fund
make venv && source .venv/bin/activate     # or use ./.venv/bin/python directly
make install                               # runtime + dev deps
cp .env.example .env                        # fill in secrets later; NEVER commit .env
make test-unit                              # fast unit tests + coverage gate
make lint                                   # ruff + mypy
make pre-push                               # full gate: lint + all tests + security (run before pushing)
```

- **Python:** dev box is **3.14** (`.venv/`); **CI runs 3.12**. Code targets 3.11+.
- **Default data source is `fixture`** (deterministic synthetic data, no credentials). The
  whole platform works with zero external access. **`DATA_SOURCE=public` gives REAL data for
  free** (Yahoo daily prices + SEC EDGAR point-in-time fundamentals, no keys; estimates/
  ownership/supply-chain raise `NotImplementedError`). Set `DATA_SOURCE=factset` only once
  FactSet entitlement lands (see §9).
- **Dev server (Jupyter):** config in `~/Documents/.claude/launch.json` (port **8889**). Note
  `preview_start` fails here (macOS TCC sandbox can't read `~/Documents`); start it from a
  shell instead:
  `.venv/bin/jupyter lab --no-browser --port=8889 --ServerApp.ip=127.0.0.1 --ServerApp.token= --ServerApp.root_dir=$(pwd)`

---

## 3. GitHub coordinates & access

- **Repo:** https://github.com/deniel-nankov/Small-little-side-hustle (public)
- **Local:** `~/Documents/yale-alpha-fund` (⚠️ the harness working dir is the *parent*
  `~/Documents`; paths like `.claude/launch.json` resolve there, not in the repo)
- **Auth (two identities — important):**
  - `gh` CLI is authenticated as **`deniel-nankov`** (repo **owner/admin**) → use `gh` for
    PRs, merges, branch protection, issues.
  - `git`/SSH pushes authenticate as **`denielnankov-quorim`** (a **collaborator** with write).
- **`main` is protected:** PRs required · required status checks = **`test` + `compliance`** ·
  **0 approvals** (you can self-merge) · admins exempt · no force-push. **Auto-merge is
  enabled** — the standard pattern is `gh pr merge <n> --squash --delete-branch --auto`.
- **Project board:** a GitHub Projects Kanban was requested but NOT built — the `gh` token
  lacks the `project` scope. To enable: user runs `gh auth refresh -s project`, then it can be
  created. Milestones + issues exist and act as the backlog in the meantime.

---

## 4. Repo structure

```
yale-alpha-fund/
├── HANDOFF.md                     ← you are here
├── README.md, Makefile, pyproject.toml, requirements*.txt, .env.example, .gitignore
├── stubs/scipy/                   ← minimal local mypy stub (see §8 gotchas)
├── .githooks/pre-push             ← opt-in gate (enable: make install-hooks)
├── .github/
│   ├── workflows/ci.yml           ← ruff→mypy→pytest→coverage→bandit→pip-audit + test report
│   ├── workflows/compliance.yml   ← runs scripts/compliance_check.py (REQUIRED check)
│   ├── workflows/codeql.yml       ← security scanning
│   ├── dependabot.yml, copilot-instructions.md, ISSUE_TEMPLATE/, PULL_REQUEST_TEMPLATE.md
├── .claude/agents/                ← repo subagents: compliance-reviewer, security-reviewer,
│                                     flow-checker, test-guardian, edge-case-hunter
├── config/
│   └── settings.py                ← the ONLY place env vars are read (pydantic-settings, SecretStr)
├── docs/                          ← ARCHITECTURE, PRINCIPLES, SECURITY, TESTING, DATA_CONTRACTS,
│                                     SIGNAL_REGISTRY, MONITORING, DEPLOYMENT, CONTRIBUTING (all written)
├── src/
│   ├── data/
│   │   ├── contracts/schemas.py   ← Pydantic data contracts (the law: frozen, extra=forbid)
│   │   ├── source/                ← DataSource ABC + FixtureSource + get_data_source() factory
│   │   ├── factset/               ← client.py (HTTP, retry, auth), source.py (FactSetSource) [Stage 2]
│   │   ├── public/                ← FREE real data: yahoo.py (prices), edgar.py (PIT fundamentals),
│   │   │                             source.py (PublicSource) — DATA_SOURCE=public, no credentials
│   │   └── market/                ← price_volume stub
│   ├── signals/
│   │   ├── construction/          ← truebeats, fundamental_factors, ownership_signal,
│   │   │                             supply_chain_signal, _common.py (zscore/rank/make_scores)
│   │   ├── discovery/             ← nvidia_agent, quanta_alpha, alpha_agent, beyond_prompting (STUBS)
│   │   ├── validation/            ← ic_calculator, pvalue_test (MadEvolve guard), decay_tester,
│   │   │                             regime_tester, backtest_runner (7-test suite → BacktestResult)
│   │   ├── combination/           ← signal_selector (de-dup), optimal_weights (Σ⁻¹μ + combine)
│   │   └── registry/signal_registry.py  ← SQLite-backed lifecycle store (audit-wired)
│   ├── portfolio/
│   │   ├── construction.py        ← vol-scaled tilt + construct_portfolio_cvar (exact LP)
│   │   ├── mean_cvar.py           ← Rockafellar-Uryasev LP via scipy.optimize.linprog
│   │   ├── constraints.py, risk.py (VaR/CVaR/scenarios)
│   ├── monitoring/                ← logger.py (structlog), audit.py (SHA-256 hash-chained log),
│   │                                 alerts.py/metrics.py (STUBS)
│   ├── utils/                     ← integrity.py (SHA-256 sidecars + atomic writes),
│   │                                 compliance.py (deterministic rule checks), dates/validators/decorators (stubs)
│   └── execution/                 ← quantconnect, madevolve (STUBS, Stage 6)
├── tests/  unit/ integration/ system/ + synth.py (deterministic test universes)
├── scripts/ compliance_check.py, daily_run.py (stub), seed_signal_registry.py (stub), setup.sh
└── notebooks/research/            ← Jupyter notebooks (minimal)
```

**181 tests pass, 1 skipped** (the FactSet live integration test, skipped without credentials).

---

## 5. Architecture / data flow (see `docs/ARCHITECTURE.md`)

- **Data contracts** (`src/data/contracts/schemas.py`) cross every module boundary — never
  raw dicts/DataFrames. Frozen, `extra="forbid"`. Key ones: `PriceData`, `EstimateData`,
  `FundamentalData`, `OwnershipData`, `SupplyChainLink`, `SignalScore`, `BacktestResult`,
  `PortfolioWeights`, `SignalStatus`.
- **DataSource abstraction** (`src/data/source/base.py`): `get_prices/estimates/fundamentals/
  ownership/supply_chain`. Two impls: **`FixtureSource`** (default, deterministic, no creds)
  and **`FactSetSource`** (real, needs entitlement). `get_data_source(settings)` picks via
  `DATA_SOURCE`.
- **The loop:** DataSource → signals (`compute_*` → `SignalScore`) → `backtest_runner.run_backtest`
  (7-test suite → `BacktestResult`) → `signal_selector` + `optimal_weights.combine_signals` →
  `construct_portfolio`/`construct_portfolio_cvar` → `PortfolioWeights`. Proven end-to-end in
  `tests/system/test_end_to_end.py`.

---

## 6. Status by stage

| Stage | Status | Notes |
|---|---|---|
| **1 · Foundation** | ✅ done | scaffold, 9 docs, config, contracts, logging, fixtures |
| **3 · Signals & validation** | ✅ done | 4 signals + full 7-test suite + registry (all on fixtures) |
| **5 · Combination & portfolio** | ✅ done | selector, optimal weights, **exact mean-CVaR LP** (#11) |
| **H · Hardening** | 🟢 4/5 | CI test reports, CodeQL+Dependabot+bandit, pre-push gate, Claude subagents. Open: **#3** (per-ticket test convention doc) |
| **C · Institutional compliance** | 🟡 4/8 | Done: #28 audit-wire registry, #29 audit-wire validation/portfolio, #30 SHA-256 sidecars, **#31 PIT leakage guard** (`src/utils/pit.py`: PITDataSource clamp+verify; wall-clock ban in analytics). Open: **#32** train/test discipline, **#33** expand compliance checker, **#34** reproducibility manifest, **#35** CODEOWNERS |
| **2 · Data layer** | 🟡 partial | **#7 done** (FactSet client + get_prices). **PR #43: `DATA_SOURCE=public` shipped** — real Yahoo prices + EDGAR PIT fundamentals, live-verified. **#8 open** (FactSet estimates/fundamentals/etc., blocked on entitlement §9); **#45 open** (EDGAR 13F ownership parser) |
| **4 · AI discovery** | ⚪ not started | #9 NeMo, #10 AlphaAgent (need NVIDIA/LLM API keys) |
| **6 · Execution & monitoring** | ⚪ not started | #12 QuantConnect, #13 monitoring alerts/dashboard |
| **7 · Live trading** | ⚪ not started | #14 pre-flight → IBKR paper → live |

---

## 7. Workflow conventions (follow these)

- **One ticket = one branch → PR → CI → self-merge.** `main` is protected; never push to it
  directly. `git checkout -b feat/<x>` → build → push → `gh pr create` → `gh pr merge <n>
  --squash --delete-branch --auto`.
- **Bottom-up, test-first:** write unit tests in the smallest leaf module first, then compose
  upward. Every ticket ships a dedicated `tests/unit/test_<name>.py`.
- **The gate (must be green before pushing):**
  ```bash
  ./.venv/bin/ruff check src/ config/ tests/ scripts/
  ./.venv/bin/mypy src/ config/
  PYTHONPATH=. ./.venv/bin/python scripts/compliance_check.py
  ./.venv/bin/python -m pytest -q
  ```
- **Watching CI:** `gh run watch <id> --exit-status` (gotcha: `gh run list --limit 1` can
  return a *stale* run just after pushing — verify `headSha` matches your commit).
- **Commit trailer:** `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.

---

## 8. Key decisions & gotchas (tribal knowledge — READ THIS)

- **Pure-stdlib analytics.** IC/Spearman/t-dist/portfolio stats are hand-written (no
  numpy/scipy) for portability across the 3.14 dev box and 3.12 CI. **Exception:** the exact
  mean-CVaR LP uses `scipy.optimize.linprog` — scipy is used **only** in `src/portfolio/`.
- **mypy config:** `python_version=3.12` + `mypy 2.1.0` (needed to parse modern numpy stubs) +
  a minimal local stub at `stubs/scipy/optimize.pyi` so mypy never parses the real numpy/scipy
  stubs (they crashed older mypy). Don't "simplify" this away.
- **The `.gitignore` bug (do NOT reintroduce):** a bare `data/` rule silently gitignored the
  entire `src/data/` source tree for several commits. It's now anchored to `/data/`. Never use
  a bare `data/` pattern.
- **CI installs the project editable** (`pip install -e . --no-deps`) so `mypy`/`pytest`
  resolve `src.*`/`config.*` deterministically.
- **Secrets:** everything via `config/settings.py` (SecretStr) from `.env` (gitignored). **Never
  read `os.environ` directly** outside settings; **never paste secrets into chat** (put them in
  `.env`). The compliance checker enforces the no-direct-env / no-hardcoded-secret rules.
- **Dev server / preview:** `preview_start` can't launch anything under `~/Documents` (macOS
  TCC sandbox denies the preview helper). Start servers from a shell instead.

---

## 9. FactSet situation (the real blocker)

- **Auth is fully solved and proven.** Both a `private_key_jwt` confidential-client and a
  `client_secret` app authenticate successfully against `https://auth.factset.com/as/token.oauth2`.
- **Every content API returns `403 Forbidden`:** `yale_edu-2408524 does not have permission to
  use /factset-global-prices/v1/prices` (and identical for Concordance, etc.). **The Yale
  account has ZERO content-API entitlements.** This is a *licensing* gap, not auth or code.
- **What unblocks it:** Yale's FactSet admin / account rep must **entitle the account** for the
  content APIs (Global Prices, Estimates Broker/Detail point-in-time, Fundamentals PIT,
  Symbology/Concordance, Ownership, Supply Chain). A draft request email is in the chat history;
  the ask is "enable these content APIs for account `YALE_EDU-2408524`." Expect a "not in the
  academic license / additional cost" conversation.
- **Code readiness:** `FactSetClient` + `FactSetSource.get_prices()` are **code-complete and
  unit-tested** (mocked) against the real Global Prices OpenAPI spec (base
  `https://api.factset.com/content`, ids like `AAPL-US`, adjust `SPLIT`/`DIV_SPIN_SPLITS`).
  Remaining code work when entitlement lands: (a) add OAuth2 token-fetch to `FactSetClient`
  (currently Basic-only; the flow is proven), (b) implement the other `get_*` methods from
  their specs. Specs the user has shared: **Global Prices** (built), **Concordance** (`~/Downloads/
  factset_concordance_api-v2-yaml.yaml`).

---

## 10. Non-negotiables (Deniel's rules — enforce always)

- **Point-in-time data only**; **no outcome / look-ahead leakage**; strict **train/test
  discipline** (out-of-sample validation).
- **SHA-256 sidecars, atomic writes, audit logs** for anything persisted
  (`src/utils/integrity.py`, `src/monitoring/audit.py`).
- **PnL primacy:** report PnL/trade, not just hit-rate (asymmetric payoffs break naive
  hit-rate analysis).
- **Never push to GitHub or change infra without asking**; background jobs / EC2 spend are
  pre-authorized. Concise, numbers-over-prose, execute-then-summarize.

---

## 11. Suggested next steps

1. **Finish Stage C** (unblocked, high-value): **#31** point-in-time leakage guard → **#32**
   train/test discipline → **#33** expand compliance checker → **#34** reproducibility manifest
   → **#35** CODEOWNERS. Bottom-up, test-first, one PR each.
2. **When FactSet entitlement lands:** add OAuth2 to `FactSetClient`, implement the other
   `get_*` methods, flip `DATA_SOURCE=factset`, run the integration smoke.
3. **Optional infra:** `gh auth refresh -s project` → build the Kanban board.

**Docs to read next:** `docs/ARCHITECTURE.md`, `docs/PRINCIPLES.md` (12 rules), `docs/TESTING.md`
(the 7-test signal suite), `docs/DATA_CONTRACTS.md`, `docs/CONTRIBUTING.md`.
