"""Call signatures and a short-lived result store.

Two problems solved by one idea.

The first is repetition: an agent that calls `get_order(id=42)` three times in
a row is stuck, and detecting that requires a stable identity for "the same
call". The second is side effects: if a run is resumed from a checkpoint and
replays a call that already charged a card, the charge happens twice.

The identity is derived from the tool name plus NORMALIZED arguments —
normalized because `{"a": 1, "b": 2}` and `{"b": 2, "a": 1}` are the same call
and a raw string hash would say otherwise.

The key is never requested from the model. Asking the model for an
idempotency key means the guarantee holds exactly as often as the model
remembers to send a stable one, which is not a guarantee.

The store's limit is stated plainly: the process can die after the tool ran
and before the result was written. Full protection requires the tool itself to
be idempotent; this narrows the window, it does not close it.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .spec import ToolResult

__all__ = ["call_signature", "IdempotencyStore"]


def call_signature(name: str, arguments: Mapping[str, Any] | str) -> str:
    """Stable identity for one call.

    Arguments accepted either as a mapping or as the raw JSON string, because
    the executor has the string and the loop has the parsed form. Unparseable
    JSON falls back to hashing the raw text: two identical malformed calls
    should still look identical.
    """
    if isinstance(arguments, str):
        try:
            parsed: Any = json.loads(arguments)
        except json.JSONDecodeError:
            parsed = {"__raw__": arguments}
    else:
        parsed = dict(arguments)
    canonical = json.dumps(parsed, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(f"{name}:{canonical}".encode()).hexdigest()
    return f"{name}:{digest[:16]}"


@dataclass
class IdempotencyStore:
    """In-memory store of recent results, keyed by call signature.

    In production this is Redis or a table with a TTL. The interface is the
    same, which is the point of keeping it this small: swapping the backend
    does not touch the executor.
    """

    ttl_s: float = 900.0
    _entries: dict[str, tuple[float, ToolResult]] = field(default_factory=dict)

    def get(self, signature: str) -> ToolResult | None:
        entry = self._entries.get(signature)
        if entry is None:
            return None
        stored_at, result = entry
        if time.monotonic() - stored_at > self.ttl_s:
            del self._entries[signature]
            return None
        return result

    def put(self, signature: str, result: ToolResult) -> None:
        self._entries[signature] = (time.monotonic(), result)

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
