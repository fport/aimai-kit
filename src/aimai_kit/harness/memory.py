"""A SQLite memory store with a deterministic write gate.

Three record types, because they answer different questions and expire
differently:

    episodic    what happened ("the customer asked to cancel order 1002")
    semantic    what is true ("this customer is on the enterprise tier")
    procedural  how to do something ("cancellations need a reason string")

The write gate is DETERMINISTIC and that is the whole design. Asking the model
"should this be remembered?" produces a store that fills with the model's own
speculation, and speculation that has been written down reads exactly like a
fact on the way back out. Rules decide instead:

    - patterns that look like secrets or personal identifiers are refused
    - transient phrasing ("right now", "today") is refused
    - the model's own inferences ("probably", "seems like") are refused

`valid_until` exists because most memories are wrong eventually. A stored
"the customer is on the trial plan" is true for thirty days and misleading
after. Recall filters on it and publishes a stale rate, so the store's decay
is visible rather than something users discover.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path

from ..provider.counters import COUNTERS

__all__ = ["MemoryKind", "MemoryRecord", "WriteRefused", "MemoryStore"]


class MemoryKind(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    valid_until TEXT
);
CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
"""

# Anything matching these never gets written. The list is short and blunt on
# purpose: a gate that tries to be clever about what counts as sensitive ends
# up with exceptions, and exceptions are how secrets get stored.
_SENSITIVE_PATTERNS = (
    re.compile(r"\b\d{13,19}\b"),  # card-like number
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),  # email
    re.compile(r"\b(?:sk|pk|api[_-]?key|token|secret|password)[-_: =]", re.I),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # national id shape
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{10,}", re.I),
)

# Phrasing that is true now and false later. Storing it produces confident
# wrong answers weeks afterwards.
_TRANSIENT_PATTERNS = (
    re.compile(r"\b(right now|currently|at the moment|today|this week)\b", re.I),
)

# The model reasoning about itself. Storing an inference launders it into a
# fact on the way back out.
_SPECULATION_PATTERNS = (
    re.compile(r"\b(probably|might be|seems like|i think|i believe|maybe)\b", re.I),
)


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    kind: MemoryKind
    content: str
    source: str
    tags: tuple[str, ...] = ()
    created_at: str = ""
    valid_until: str | None = None
    id: int | None = None

    @property
    def is_stale(self) -> bool:
        if not self.valid_until:
            return False
        return date.fromisoformat(self.valid_until) < datetime.now(UTC).date()


class WriteRefused(Exception):
    """The write gate rejected this content. The reason is the message."""


class MemoryStore:
    """SQLite-backed store with a deterministic write gate."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    # --- write gate -------------------------------------------------------

    @staticmethod
    def check(content: str) -> str | None:
        """Return a refusal reason, or None if the content may be stored."""
        for pattern in _SENSITIVE_PATTERNS:
            if pattern.search(content):
                return "looks like a credential or personal identifier"
        for pattern in _TRANSIENT_PATTERNS:
            if pattern.search(content):
                return "phrased as something that is only true right now"
        for pattern in _SPECULATION_PATTERNS:
            if pattern.search(content):
                return "reads as speculation rather than an observed fact"
        if len(content.strip()) < 10:
            return "too short to be useful on recall"
        return None

    def write(
        self,
        kind: MemoryKind,
        content: str,
        *,
        source: str,
        tags: Sequence[str] = (),
        valid_until: date | str | None = None,
    ) -> MemoryRecord:
        """Store a memory, or raise `WriteRefused` with the reason."""
        refusal = self.check(content)
        if refusal is not None:
            COUNTERS.increment("memory_writes_refused_total", reason=refusal[:24])
            raise WriteRefused(f"not stored: {refusal}")

        until = (
            valid_until.isoformat() if isinstance(valid_until, date) else valid_until
        )
        created = datetime.now(UTC).isoformat()
        cursor = self._conn.execute(
            "INSERT INTO memories (kind, content, source, tags, created_at, "
            "valid_until) VALUES (?, ?, ?, ?, ?, ?)",
            (kind.value, content, source, ",".join(tags), created, until),
        )
        self._conn.commit()
        COUNTERS.increment("memory_writes_total", kind=kind.value)
        return MemoryRecord(
            kind=kind,
            content=content,
            source=source,
            tags=tuple(tags),
            created_at=created,
            valid_until=until,
            id=cursor.lastrowid,
        )

    # --- recall -----------------------------------------------------------

    def recall(
        self,
        query: str = "",
        *,
        kind: MemoryKind | None = None,
        include_stale: bool = False,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        """Fetch memories, filtering out expired ones by default.

        The stale rate is published as a counter rather than logged: a store
        where half the recalls are dropping expired records is not a working
        memory, and that fact should reach a dashboard without anyone reading
        a log line.
        """
        sql = "SELECT * FROM memories WHERE 1=1"
        params: list[object] = []
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind.value)
        if query:
            sql += " AND content LIKE ?"
            params.append(f"%{query}%")
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit * 3 if not include_stale else limit)

        rows = [self._row(r) for r in self._conn.execute(sql, params)]
        if include_stale:
            return rows[:limit]

        fresh = [r for r in rows if not r.is_stale]
        stale_count = len(rows) - len(fresh)
        if rows:
            COUNTERS.increment("memory_recall_total")
            if stale_count:
                COUNTERS.increment("memory_stale_filtered_total", value=stale_count)
        return fresh[:limit]

    def stale_ratio(self) -> float:
        """Share of stored records that have expired."""
        rows = [self._row(r) for r in self._conn.execute("SELECT * FROM memories")]
        if not rows:
            return 0.0
        return round(sum(r.is_stale for r in rows) / len(rows), 3)

    @staticmethod
    def _row(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            kind=MemoryKind(row["kind"]),
            content=row["content"],
            source=row["source"],
            tags=tuple(t for t in row["tags"].split(",") if t),
            created_at=row["created_at"],
            valid_until=row["valid_until"],
            id=row["id"],
        )

    def __len__(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
