"""Tamper-evident audit log (Stage H).

An append-only JSONL trail of significant decisions (signal validation, promotions,
portfolio construction, trades). Each entry carries a SHA-256 of its canonical content and
a ``prev_hash`` chaining it to the previous entry, so any later edit or deletion is
detectable via :meth:`AuditLog.verify`. This implements the team's non-negotiables:
SHA-256 integrity, audit logging, append-only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.monitoring.logger import get_logger

_log = get_logger(__name__)


def _canonical(entry: dict[str, Any]) -> str:
    """Deterministic JSON serialization used for hashing (sorted keys, no whitespace)."""
    return json.dumps(entry, sort_keys=True, separators=(",", ":"))


class AuditLog:
    """Append-only, hash-chained audit trail backed by a JSONL file."""

    def __init__(self, path: str | Path) -> None:
        """Open (or create) the audit log.

        Args:
            path: Path to the JSONL audit file.
        """
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)

    def record(self, event: str, payload: dict[str, Any], actor: str = "system") -> str:
        """Append an event and return its SHA-256 hash.

        Args:
            event: Short event key, e.g. ``"signal.promoted"``.
            payload: JSON-serializable details of the decision.
            actor: Who/what produced the event.

        Returns:
            The hex SHA-256 digest of the recorded entry.
        """
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "actor": actor,
            "event": event,
            "payload": payload,
            "prev_hash": self._last_hash(),
        }
        digest = hashlib.sha256(_canonical(entry).encode()).hexdigest()
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({**entry, "hash": digest}) + "\n")
        _log.info("audit.record", event_type=event, actor=actor, hash=digest[:12])
        return digest

    def entries(self) -> list[dict[str, Any]]:
        """Return all recorded entries in order."""
        out: list[dict[str, Any]] = []
        with self._path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def verify(self) -> bool:
        """Recompute hashes and the prev-hash chain; return False if anything was tampered."""
        prev: str | None = None
        for stored in self.entries():
            recorded_hash = stored.get("hash")
            content = {k: v for k, v in stored.items() if k != "hash"}
            if hashlib.sha256(_canonical(content).encode()).hexdigest() != recorded_hash:
                return False
            if content.get("prev_hash") != prev:
                return False
            prev = recorded_hash
        return True

    def _last_hash(self) -> str | None:
        entries = self.entries()
        if not entries:
            return None
        last_hash = entries[-1].get("hash")
        return str(last_hash) if last_hash is not None else None
