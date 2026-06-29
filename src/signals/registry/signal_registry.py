"""Signal registry: lifecycle store and Python wrapper (Stage 3).

SQLite-backed (stdlib ``sqlite3``, so it runs and tests anywhere with no DB service); the
schema mirrors docs/SIGNAL_REGISTRY.md and is Postgres-ready — a future adapter can target
``DATABASE_URL`` with the same model. Tracks every signal through its lifecycle::

    DISCOVERED -> VALIDATED -> STAGING -> PRODUCTION -> RETIRED

Transitions are validated; invalid jumps (e.g. DISCOVERED -> PRODUCTION) raise. Any
non-retired signal may be retired directly.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from src.data.contracts.schemas import SignalStatus
from src.monitoring.logger import get_logger

_log = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _require_dt(value: str | None) -> datetime:
    if value is None:
        raise ValueError("missing required timestamp in registry row")
    return datetime.fromisoformat(value)


# Allowed lifecycle transitions (any non-retired status may also go straight to RETIRED).
_ALLOWED_TRANSITIONS: dict[SignalStatus, set[SignalStatus]] = {
    SignalStatus.discovered: {SignalStatus.validated, SignalStatus.retired},
    SignalStatus.validated: {SignalStatus.staging, SignalStatus.retired},
    SignalStatus.staging: {SignalStatus.production, SignalStatus.retired},
    SignalStatus.production: {SignalStatus.retired},
    SignalStatus.retired: set(),
}


class SignalRecord(BaseModel):
    """One row of the signal registry."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    version: str
    status: SignalStatus
    description: str
    category: str | None = None
    data_sources: list[str] = Field(default_factory=list)
    point_in_time: bool = True
    created_at: datetime = Field(default_factory=_now)
    validated_at: datetime | None = None
    promoted_at: datetime | None = None
    retired_at: datetime | None = None
    mean_ic: float | None = None
    icir: float | None = None
    sharpe: float | None = None
    holding_period: int | None = None
    universe: str | None = None
    notes: str | None = None


class TransitionError(RuntimeError):
    """Raised on an invalid lifecycle transition."""


class DuplicateSignalError(RuntimeError):
    """Raised when registering a signal whose name already exists."""


class SignalNotFoundError(KeyError):
    """Raised when a signal name is not in the registry."""


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS signals (
    name           TEXT PRIMARY KEY,
    version        TEXT NOT NULL,
    status         TEXT NOT NULL,
    description    TEXT NOT NULL,
    category       TEXT,
    data_sources   TEXT NOT NULL,
    point_in_time  INTEGER NOT NULL,
    created_at     TEXT NOT NULL,
    validated_at   TEXT,
    promoted_at    TEXT,
    retired_at     TEXT,
    mean_ic        REAL,
    icir           REAL,
    sharpe         REAL,
    holding_period INTEGER,
    universe       TEXT,
    notes          TEXT
);
"""


class SignalRegistry:
    """SQLite-backed registry of all signals and their lifecycle state."""

    def __init__(self, db_path: str = ":memory:") -> None:
        """Open (or create) the registry database.

        Args:
            db_path: SQLite path, or ``":memory:"`` for an ephemeral in-process DB (tests).
        """
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    def register(self, record: SignalRecord) -> SignalRecord:
        """Insert a new signal.

        Args:
            record: The signal to register (typically status DISCOVERED or VALIDATED).

        Returns:
            The stored record.

        Raises:
            DuplicateSignalError: if a signal with the same name already exists.
        """
        if self.get(record.name) is not None:
            raise DuplicateSignalError(record.name)
        self._conn.execute(
            """INSERT INTO signals VALUES
               (:name,:version,:status,:description,:category,:data_sources,:point_in_time,
                :created_at,:validated_at,:promoted_at,:retired_at,:mean_ic,:icir,:sharpe,
                :holding_period,:universe,:notes)""",
            self._to_row(record),
        )
        self._conn.commit()
        _log.info("registry.register", name=record.name, status=record.status.value)
        return record

    def get(self, name: str) -> SignalRecord | None:
        """Return the signal record, or None if absent."""
        row = self._conn.execute("SELECT * FROM signals WHERE name = ?", (name,)).fetchone()
        return self._from_row(row) if row is not None else None

    def require(self, name: str) -> SignalRecord:
        """Return the signal record or raise :class:`SignalNotFoundError`."""
        record = self.get(name)
        if record is None:
            raise SignalNotFoundError(name)
        return record

    def list_signals(self, status: SignalStatus | None = None) -> list[SignalRecord]:
        """Return all signals, optionally filtered by status, ordered by name."""
        if status is None:
            rows = self._conn.execute("SELECT * FROM signals ORDER BY name").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM signals WHERE status = ? ORDER BY name", (status.value,)
            ).fetchall()
        return [self._from_row(r) for r in rows]

    def update_status(self, name: str, new_status: SignalStatus) -> SignalRecord:
        """Transition a signal to ``new_status``, validating the move and stamping the time.

        Args:
            name: Signal to transition.
            new_status: Target lifecycle state.

        Returns:
            The updated record.

        Raises:
            SignalNotFoundError: if the signal does not exist.
            TransitionError: if the transition is not allowed.
        """
        record = self.require(name)
        if new_status not in _ALLOWED_TRANSITIONS[record.status]:
            raise TransitionError(
                f"{name}: cannot move {record.status.value} -> {new_status.value}"
            )
        now = _now()
        stamps: dict[str, datetime] = {}
        if new_status is SignalStatus.validated:
            stamps["validated_at"] = now
        elif new_status is SignalStatus.production:
            stamps["promoted_at"] = now
        elif new_status is SignalStatus.retired:
            stamps["retired_at"] = now
        updated = record.model_copy(update={"status": new_status, **stamps})
        self._save(updated)
        _log.info("registry.transition", name=name, frm=record.status.value, to=new_status.value)
        return updated

    def update_metrics(
        self,
        name: str,
        mean_ic: float | None = None,
        icir: float | None = None,
        sharpe: float | None = None,
    ) -> SignalRecord:
        """Update tracked performance metrics; only provided (non-None) fields change."""
        record = self.require(name)
        updated = record.model_copy(
            update={
                "mean_ic": record.mean_ic if mean_ic is None else mean_ic,
                "icir": record.icir if icir is None else icir,
                "sharpe": record.sharpe if sharpe is None else sharpe,
            }
        )
        self._save(updated)
        return updated

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __enter__(self) -> SignalRegistry:
        """Enter a context manager that closes the connection on exit."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close the database connection on context exit."""
        self.close()

    # ------------------------------------------------------------------ internals
    def _save(self, record: SignalRecord) -> None:
        self._conn.execute(
            """UPDATE signals SET
                 version=:version, status=:status, description=:description, category=:category,
                 data_sources=:data_sources, point_in_time=:point_in_time, created_at=:created_at,
                 validated_at=:validated_at, promoted_at=:promoted_at, retired_at=:retired_at,
                 mean_ic=:mean_ic, icir=:icir, sharpe=:sharpe, holding_period=:holding_period,
                 universe=:universe, notes=:notes
               WHERE name=:name""",
            self._to_row(record),
        )
        self._conn.commit()

    @staticmethod
    def _to_row(record: SignalRecord) -> dict[str, object]:
        return {
            "name": record.name,
            "version": record.version,
            "status": record.status.value,
            "description": record.description,
            "category": record.category,
            "data_sources": json.dumps(record.data_sources),
            "point_in_time": int(record.point_in_time),
            "created_at": _iso(record.created_at),
            "validated_at": _iso(record.validated_at),
            "promoted_at": _iso(record.promoted_at),
            "retired_at": _iso(record.retired_at),
            "mean_ic": record.mean_ic,
            "icir": record.icir,
            "sharpe": record.sharpe,
            "holding_period": record.holding_period,
            "universe": record.universe,
            "notes": record.notes,
        }

    @staticmethod
    def _from_row(row: sqlite3.Row) -> SignalRecord:
        return SignalRecord(
            name=row["name"],
            version=row["version"],
            status=SignalStatus(row["status"]),
            description=row["description"],
            category=row["category"],
            data_sources=json.loads(row["data_sources"]),
            point_in_time=bool(row["point_in_time"]),
            created_at=_require_dt(row["created_at"]),
            validated_at=_parse_dt(row["validated_at"]),
            promoted_at=_parse_dt(row["promoted_at"]),
            retired_at=_parse_dt(row["retired_at"]),
            mean_ic=row["mean_ic"],
            icir=row["icir"],
            sharpe=row["sharpe"],
            holding_period=row["holding_period"],
            universe=row["universe"],
            notes=row["notes"],
        )
