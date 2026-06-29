"""CLI: run deterministic compliance checks; exit non-zero on any violation (Stage H).

Used by the Compliance CI workflow on every PR. Run locally with:
    python scripts/compliance_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.utils.compliance import run_checks


def main() -> int:
    """Run the checks against the repo root and report. Returns a process exit code."""
    root = Path(__file__).resolve().parents[1]
    violations = run_checks(root)
    if violations:
        sys.stdout.write("COMPLIANCE VIOLATIONS:\n")
        for violation in violations:
            sys.stdout.write(f"  - {violation}\n")
        return 1
    sys.stdout.write("compliance: clean\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
