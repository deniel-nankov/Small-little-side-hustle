"""Unit tests for the deterministic compliance checks (ticket: compliance controls, Stage H)."""

from __future__ import annotations

import textwrap
from pathlib import Path

from src.utils.compliance import (
    check_no_bare_except,
    check_no_direct_env,
    check_no_hardcoded_secrets,
    check_no_print,
    run_checks,
)

_REPO = Path(__file__).resolve().parents[2]


def test_repo_is_compliant() -> None:
    # Our own source must pass every compliance check.
    assert run_checks(_REPO) == []


def _write(tmp_path: Path, rel: str, code: str) -> Path:
    target = tmp_path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(code))
    return tmp_path


def test_flags_print_in_library_code(tmp_path: Path) -> None:
    root = _write(tmp_path, "src/x.py", "def f():\n    print('hi')\n")
    assert check_no_print(root)


def test_flags_bare_except(tmp_path: Path) -> None:
    root = _write(tmp_path, "src/x.py", "try:\n    pass\nexcept:\n    pass\n")
    assert check_no_bare_except(root)


def test_flags_direct_env_access(tmp_path: Path) -> None:
    root = _write(tmp_path, "src/x.py", "import os\nA = os.environ['X']\n")
    assert check_no_direct_env(root)


def test_allows_env_access_in_settings(tmp_path: Path) -> None:
    root = _write(tmp_path, "config/settings.py", "import os\nA = os.getenv('X')\n")
    assert check_no_direct_env(root) == []


def test_flags_hardcoded_secret(tmp_path: Path) -> None:
    root = _write(tmp_path, "src/x.py", 'api_key = "abc123secret"\n')
    assert check_no_hardcoded_secrets(root)
