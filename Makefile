# ============================================================================
#  yale-alpha-fund — developer shortcuts.  Run `make help` for the list.
#  Uses the project venv at ./.venv if present, else falls back to system python.
# ============================================================================
PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
PIP := $(PY) -m pip

.DEFAULT_GOAL := help

.PHONY: help install venv test-unit test-integration test-all lint format audit \
        run-daily check-secrets setup-db cov security pre-push install-hooks

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

venv:  ## Create the project virtualenv
	python3 -m venv .venv

install:  ## Install runtime + dev dependencies into the venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt -r requirements-dev.txt

test-unit:  ## Fast isolated unit tests with coverage gate on src/signals
	$(PY) -m pytest tests/unit/ -v --cov=src/signals --cov-report=term-missing

test-integration:  ## Integration tests (may hit sandbox APIs)
	$(PY) -m pytest tests/integration/ -v

test-all:  ## Every test level
	$(PY) -m pytest tests/ -v

cov:  ## Full-source coverage report
	$(PY) -m pytest tests/unit/ --cov=src --cov-report=term-missing

lint:  ## Static analysis: ruff + mypy
	$(PY) -m ruff check src/ tests/ config/
	$(PY) -m mypy src/ config/

format:  ## Auto-format with ruff
	$(PY) -m ruff format src/ tests/ config/
	$(PY) -m ruff check --fix src/ tests/ config/

audit:  ## Check installed deps for known CVEs
	$(PY) -m pip_audit

run-daily:  ## Entry point for the daily automated pipeline
	$(PY) scripts/daily_run.py

setup-db:  ## Seed the signal registry table
	$(PY) scripts/seed_signal_registry.py

check-secrets:  ## Guard: refuse to stage anything that looks like a credential
	@git diff --cached | grep -iE "api_key|secret|password|token" \
		&& { echo "SECRET DETECTED - DO NOT COMMIT"; exit 1; } \
		|| echo "Clean"

security:  ## Security scan: bandit (SAST) + pip-audit (dependency CVEs)
	$(PY) -m bandit -r src/ -ll
	$(PY) -m pip_audit || true

pre-push: lint test-all security  ## Full gate to run before pushing (lint + tests + security)
	@echo "pre-push gate passed — safe to push."

install-hooks:  ## Enable the opt-in git pre-push hook (runs 'make pre-push')
	git config core.hooksPath .githooks
	@echo "Enabled .githooks: 'git push' now runs 'make pre-push' first."
