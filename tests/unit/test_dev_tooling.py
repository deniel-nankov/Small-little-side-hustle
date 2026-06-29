"""Unit tests for the pre-push gate tooling (ticket: Pre-push test gate, Stage H)."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_pre_push_hook_exists_and_runs_the_gate() -> None:
    hook = _ROOT / ".githooks" / "pre-push"
    assert hook.exists(), "pre-push hook script is missing"
    assert "make pre-push" in hook.read_text()


def test_makefile_exposes_gate_and_hook_targets() -> None:
    makefile = (_ROOT / "Makefile").read_text()
    assert "pre-push:" in makefile
    assert "install-hooks:" in makefile
    # The gate must chain lint + the full suite + security.
    assert "pre-push: lint test-all security" in makefile
