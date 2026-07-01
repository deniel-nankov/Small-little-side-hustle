"""Data-integrity helpers: SHA-256 sidecars + atomic writes (Stage C, #30).

Implements two of the team's non-negotiables for persisted artifacts:

* **Atomic writes** — write to a temp file in the same directory, fsync, then atomically
  ``replace`` it into place, so a crash never leaves a half-written file.
* **SHA-256 sidecars** — every artifact is written alongside a ``<name>.sha256`` file
  containing its digest, and :func:`verify_sidecar` re-checks integrity later.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

_CHUNK = 1 << 20  # 1 MiB


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    """Return the hex SHA-256 digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """Atomically write ``data`` to ``path`` (temp file + fsync + atomic replace).

    Args:
        path: Destination path (parent directories are created if needed).
        data: Bytes to write.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_text(path: str | Path, text: str) -> None:
    """Atomically write ``text`` (UTF-8) to ``path``."""
    atomic_write_bytes(path, text.encode("utf-8"))


def sidecar_path(path: str | Path) -> Path:
    """Return the ``.sha256`` sidecar path for ``path``."""
    p = Path(path)
    return p.with_name(p.name + ".sha256")


def write_with_sidecar(path: str | Path, data: bytes) -> str:
    """Atomically write ``data`` and its ``.sha256`` sidecar; return the digest.

    Args:
        path: Destination path for the artifact.
        data: Bytes to write.

    Returns:
        The hex SHA-256 digest recorded in the sidecar.
    """
    digest = sha256_bytes(data)
    atomic_write_bytes(path, data)
    atomic_write_text(sidecar_path(path), f"{digest}  {Path(path).name}\n")
    return digest


def verify_sidecar(path: str | Path) -> bool:
    """Return True iff the artifact's current digest matches its ``.sha256`` sidecar.

    Returns False if the file or its sidecar is missing, or the digests differ.
    """
    target = Path(path)
    sidecar = sidecar_path(target)
    if not target.exists() or not sidecar.exists():
        return False
    recorded = sidecar.read_text(encoding="utf-8").split()[0]
    return recorded == sha256_file(target)
