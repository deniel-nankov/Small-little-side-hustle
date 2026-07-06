"""Deterministic compliance checks over the codebase (Stage H).

Small, fast, dependency-free guards that enforce the project's non-negotiable rules in CI on
every PR — the always-on counterpart to the LLM review. Each check returns a list of
``path:line: message`` violations; :func:`run_checks` aggregates them. The CLI wrapper
``scripts/compliance_check.py`` exits non-zero when any violation is found.

Rules enforced (see docs/PRINCIPLES.md):

* No direct ``os.environ`` / ``os.getenv`` outside ``config/settings.py`` (Rule 4).
* No ``print()`` in library code — use the structured logger (Rule 9).
* No bare ``except:`` — no silent failures (Rule 2).
* No obvious hardcoded credentials (Rule 4 / SECURITY.md).
* No wall-clock time in analytics code (``src/signals``, ``src/portfolio``) — signals must
  be driven by an explicit as-of date, never ``date.today()`` (#31, look-ahead risk).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from pathlib import Path

_SCAN_DIRS = ("src", "config")
_SELF = "src/utils/compliance.py"  # this file legitimately contains the keywords
_ENV_ALLOWED = ("config/settings.py",)

_ENV_RE = re.compile(r"os\.(environ|getenv)\b")
_PRINT_RE = re.compile(r"(?:^|[^.\w])print\s*\(")
_BARE_EXCEPT_RE = re.compile(r"except\s*:")
_SECRET_RE = re.compile(
    r"\b(password|secret|api_key|token)\b\s*=\s*['\"][^'\"]+['\"]", re.IGNORECASE
)

# Wall-clock access is a look-ahead / reproducibility hazard in analytics code (#31).
_ANALYTICS_DIRS = ("src/signals", "src/portfolio")
_WALLCLOCK_ALLOWED = ("src/signals/registry/signal_registry.py",)  # bookkeeping timestamps
_WALLCLOCK_RE = re.compile(r"\b(date\.today|datetime\.now|datetime\.utcnow|time\.time)\s*\(")


def _iter_py(root: Path, dirs: Sequence[str] = _SCAN_DIRS) -> Iterator[tuple[str, Path]]:
    for directory in dirs:
        for path in sorted((root / directory).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel != _SELF:
                yield rel, path


def _scan(
    root: Path,
    regex: re.Pattern[str],
    message: str,
    allowed: Sequence[str] = (),
    dirs: Sequence[str] = _SCAN_DIRS,
) -> list[str]:
    violations: list[str] = []
    for rel, path in _iter_py(root, dirs):
        if rel in allowed:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if regex.search(line):
                violations.append(f"{rel}:{lineno}: {message}")
    return violations


def check_no_direct_env(root: Path) -> list[str]:
    """Flag direct environment access outside config/settings.py."""
    return _scan(root, _ENV_RE, "direct os.environ/os.getenv (use config.settings)", _ENV_ALLOWED)


def check_no_print(root: Path) -> list[str]:
    """Flag ``print()`` in library code."""
    return _scan(root, _PRINT_RE, "print() in library code (use the logger)")


def check_no_bare_except(root: Path) -> list[str]:
    """Flag bare ``except:`` clauses."""
    return _scan(root, _BARE_EXCEPT_RE, "bare except (no silent failures)")


def check_no_hardcoded_secrets(root: Path) -> list[str]:
    """Flag obvious hardcoded credential literals."""
    return _scan(root, _SECRET_RE, "possible hardcoded credential")


def check_no_wallclock_in_analytics(root: Path) -> list[str]:
    """Flag wall-clock time in signal/portfolio code (look-ahead risk, #31)."""
    return _scan(
        root,
        _WALLCLOCK_RE,
        "wall-clock time in analytics code (pass an explicit as-of date)",
        _WALLCLOCK_ALLOWED,
        dirs=_ANALYTICS_DIRS,
    )


def run_checks(root: Path) -> list[str]:
    """Run all compliance checks and return the aggregated list of violations.

    Args:
        root: Repository root.

    Returns:
        A list of ``path:line: message`` strings; empty means compliant.
    """
    return [
        *check_no_direct_env(root),
        *check_no_print(root),
        *check_no_bare_except(root),
        *check_no_hardcoded_secrets(root),
        *check_no_wallclock_in_analytics(root),
    ]
