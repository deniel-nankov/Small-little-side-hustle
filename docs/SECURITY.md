# Security

## Secrets management

- All credentials live in a local `.env` file. **`.env` is never committed** — it is in
  `.gitignore` from the first commit.
- `.env.example` is committed with **placeholder values only**. It is the canonical list of
  every variable the system reads.
- Every secret is loaded through `config/settings.py` and stored as a Pydantic
  `SecretStr`, so it is masked in logs and `repr()`. **No module reads `os.environ`
  directly** (PRINCIPLES.md Rule 4).
- In production, inject credentials as OS environment variables (or a secrets manager) —
  do **not** ship a `.env` file to production hosts.
- **Rotate all API keys every 90 days.** Put a recurring calendar reminder on the team.
- If a key is ever committed: (1) rotate it immediately at the provider, (2) remove it from
  git history (`git filter-repo` preferred over the deprecated `git filter-branch`),
  (3) force-push the cleaned history, (4) note the incident.

## Data security

- **FactSet data is licensed.** Never share it publicly or store it in a public repo.
- All local data lives under `data/`, which is git-ignored. Synthetic fixture data is the
  only data that may appear in the repo, and it is clearly tagged `data_source="fixture"`.
- Database credentials are never in code — always environment variables (`DATABASE_URL`).
- **Never log actual credential values**, even at `DEBUG`. The `SecretStr` type enforces
  this; do not call `.get_secret_value()` inside a log statement.

## Access control

- `main` is a protected branch: no direct pushes, ≥1 review required, all CI checks must
  pass, and these settings cannot be bypassed.
- All changes go through pull requests.
- CI/CD uses GitHub Actions **secrets**, never credentials stored in workflow files.

## Dependency security

- Run `make audit` (`pip-audit`) at least monthly and in CI.
- Pin all dependency versions in `requirements.txt` (single source of truth for installs).
- Review dependency updates before merging.

## Operational guardrails (money)

- This repo can route real orders. Live trading is gated by the pre-flight checklist in
  [DEPLOYMENT.md](DEPLOYMENT.md) — including a human sign-off.
- Interactive Brokers **paper trading** must be confirmed working before switching to live.
- Position-size caps and stop-loss rules are enforced in code (`src/portfolio/constraints.py`,
  `src/portfolio/risk.py`), not left to discretion.
