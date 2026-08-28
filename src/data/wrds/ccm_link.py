"""CRSP/Compustat Merged link hygiene.

Joining Compustat fundamentals to CRSP prices runs through ``crsp.ccmxpf_lnkhist``, and
the table is mostly unusable: measured live, 123,388 rows of which only **LC (17,932)**
and **LU (15,945)** are research-grade — the remaining ~73% are unresearched (NR, NU) or
structural variants (LX, LD, LN, LS, NP) that must never be joined on.

Two look-ahead paths open up if the link is used naively:

* **Ignoring the date range** attaches a company's financials to a security in periods
  when the link was not valid — post-merger figures landing on a pre-merger stub.
* **Ignoring ``linkprim``** returns secondary and joiner rows alongside the primary one,
  silently duplicating a name and double-weighting it in a cross-section.

26,386 links are open-ended (null ``linkenddt``) and are treated as still valid.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from src.monitoring.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

_log = get_logger(__name__)

LINK_TABLE = "crsp.ccmxpf_lnkhist"

#: The only research-grade link types. LC = link confirmed, LU = link unconfirmed but
#: researched. Everything else is unresearched or a structural duplicate.
USABLE_LINKTYPES = frozenset({"LC", "LU"})

#: Primary links only. P = primary security, C = primary (Compustat-assigned). N and J
#: are secondary/joiner rows that duplicate a company.
USABLE_LINKPRIM = frozenset({"P", "C"})


def _to_date(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


@dataclass(frozen=True)
class CCMLink:
    """One research-grade gvkey <-> permno link, valid over a date window."""

    gvkey: str
    permno: int
    linktype: str
    linkprim: str
    start: date
    end: date | None  # None = still open

    def covers(self, on_date: date) -> bool:
        """True if the link was valid on ``on_date`` (both boundaries inclusive)."""
        if on_date < self.start:
            return False
        return self.end is None or on_date <= self.end


def parse_link_row(row: dict[str, Any]) -> CCMLink | None:
    """Parse one link row, rejecting anything not research-grade.

    Args:
        row: Raw ``crsp.ccmxpf_lnkhist`` row.

    Returns:
        The link, or None when the row's type/primacy is unusable, its permno is
        missing, or it carries no start date.
    """
    if row.get("linktype") not in USABLE_LINKTYPES:
        return None
    if row.get("linkprim") not in USABLE_LINKPRIM:
        return None
    raw_permno, gvkey = row.get("lpermno"), row.get("gvkey")
    start = _to_date(row.get("linkdt"))
    if raw_permno in (None, "") or not gvkey or start is None:
        return None
    try:
        permno = int(float(raw_permno))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return CCMLink(
        gvkey=str(gvkey),
        permno=permno,
        linktype=str(row["linktype"]),
        linkprim=str(row["linkprim"]),
        start=start,
        end=_to_date(row.get("linkenddt")),
    )


class CCMLinkIndex:
    """Date-aware, pre-filtered gvkey <-> permno resolver."""

    def __init__(self, links: Sequence[CCMLink], *, rejected: int) -> None:
        """Build the index from already-parsed links.

        Args:
            links: Research-grade links only.
            rejected: How many raw rows were filtered out (for the hygiene report).
        """
        self._by_gvkey: dict[str, list[CCMLink]] = defaultdict(list)
        self._by_permno: dict[int, list[CCMLink]] = defaultdict(list)
        for link in links:
            self._by_gvkey[link.gvkey].append(link)
            self._by_permno[link.permno].append(link)
        self.usable = len(links)
        self.rejected = rejected

    @classmethod
    def from_rows(cls, rows: Sequence[dict[str, Any]]) -> CCMLinkIndex:
        """Build from raw WRDS rows, filtering to research-grade links.

        Args:
            rows: Raw ``crsp.ccmxpf_lnkhist`` rows.

        Returns:
            A ready index; the filtered-out count is retained for hygiene reporting.
        """
        links = [link for link in (parse_link_row(r) for r in rows) if link is not None]
        index = cls(links, rejected=len(rows) - len(links))
        _log.info(
            "ccm.link_index_built",
            usable=index.usable,
            rejected=index.rejected,
            usable_fraction=round(index.usable_fraction, 4),
        )
        return index

    @property
    def usable_fraction(self) -> float:
        """Share of raw rows that survived filtering (live: ~0.27)."""
        total = self.usable + self.rejected
        return self.usable / total if total else 0.0

    def permno_for_gvkey(self, gvkey: str, on_date: date) -> int | None:
        """Return the permno linked to ``gvkey`` on ``on_date``, or None."""
        for link in self._by_gvkey.get(str(gvkey), ()):
            if link.covers(on_date):
                return link.permno
        return None

    def gvkey_for_permno(self, permno: int, on_date: date) -> str | None:
        """Return the gvkey linked to ``permno`` on ``on_date``, or None."""
        for link in self._by_permno.get(int(permno), ()):
            if link.covers(on_date):
                return link.gvkey
        return None
