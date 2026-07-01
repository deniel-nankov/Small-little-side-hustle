"""Unit tests for data-integrity helpers (ticket: SHA-256 sidecars + atomic writes, #30)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.utils.integrity import (
    atomic_write_bytes,
    sha256_bytes,
    sha256_file,
    sidecar_path,
    verify_sidecar,
    write_with_sidecar,
)


def test_sha256_bytes_matches_hashlib() -> None:
    assert sha256_bytes(b"hello") == hashlib.sha256(b"hello").hexdigest()


def test_atomic_write_creates_file_and_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "a.bin"
    atomic_write_bytes(target, b"data")
    assert target.read_bytes() == b"data"


def test_atomic_write_leaves_no_temp_files(tmp_path: Path) -> None:
    atomic_write_bytes(tmp_path / "a.bin", b"x")
    assert [p.name for p in tmp_path.iterdir()] == ["a.bin"]


def test_sha256_file_matches_bytes(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"content")
    assert sha256_file(path) == sha256_bytes(b"content")


def test_write_with_sidecar_records_digest_and_verifies(tmp_path: Path) -> None:
    path = tmp_path / "artifact.parquet"
    digest = write_with_sidecar(path, b"payload")
    assert digest == sha256_bytes(b"payload")
    assert sidecar_path(path).read_text(encoding="utf-8").startswith(digest)
    assert verify_sidecar(path) is True


def test_verify_fails_after_tampering(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    write_with_sidecar(path, b"payload")
    path.write_bytes(b"tampered!")
    assert verify_sidecar(path) is False


def test_verify_fails_without_sidecar(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"x")
    assert verify_sidecar(path) is False
