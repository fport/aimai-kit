"""Block ordering that keeps the cache prefix stable.

Provider prompt caching works on PREFIX matching: the part of the request
that is byte-identical from the beginning is served from cache, everything
after the first differing byte is reprocessed. That single sentence dictates
the whole block order:

    INVARIANT first, VARIABLE last.

Order: system prompt -> trust-boundary instruction -> schema -> static
examples -> tool definitions || then: retrieval results -> user message.

The most common mistake is putting a timestamp or a request id in the system
prompt. A system prompt containing `datetime.now()` invalidates the cache on
EVERY request, and the symptom is subtle — the system keeps working, only the
bill goes up tenfold. `prefix_signature` exists for that: it is pinned in a
test and breaks the moment a variable field leaks into the prefix.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

__all__ = ["stable_system_blocks", "prefix_text", "prefix_signature"]


def stable_system_blocks(
    system_text: str,
    *,
    trust_instruction: str | None = None,
    schema: Mapping[str, object] | None = None,
    examples: Sequence[str] = (),
    tool_definitions: Sequence[Mapping[str, object]] = (),
) -> tuple[str, ...]:
    """Produce the cache-prefix blocks in a FIXED order.

    The function is deliberately pure: same input, same output, and nothing
    here reads the clock, a random source or the environment. That is the
    precondition for a stable prefix.

    The schema is serialized with `sort_keys=True`: Python dicts preserve
    insertion order, so a reordering in the code that builds the schema would
    produce different bytes for the same schema. Sorting closes that silent
    invalidation path.
    """
    blocks: list[str] = [system_text.strip()]

    if trust_instruction:
        blocks.append(trust_instruction.strip())

    if schema is not None:
        blocks.append(
            "Output schema (produce a single JSON object matching it):\n"
            + json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True)
        )

    if tool_definitions:
        blocks.append(
            "Available tools:\n"
            + json.dumps(
                list(tool_definitions), ensure_ascii=False, indent=2, sort_keys=True
            )
        )

    # Examples go near the END: models follow format and examples better when
    # they sit late in the prompt, and since they are static they are still
    # inside the cached prefix.
    for i, example in enumerate(examples, start=1):
        blocks.append(f"Example {i}:\n{example.strip()}")

    return tuple(blocks)


def prefix_text(blocks: Sequence[str]) -> str:
    """Join blocks into one system message. The separator is fixed."""
    return "\n\n---\n\n".join(blocks)


def prefix_signature(blocks: Sequence[str]) -> str:
    """Byte-level signature of the prefix.

    Pinned in a test. When it changes the test breaks and whoever changed it
    has to ask "did I mean to?". If the prompt change was intentional,
    updating the signature is one line; if it was accidental, this test is
    the only thing that catches it.
    """
    return hashlib.sha256(prefix_text(blocks).encode("utf-8")).hexdigest()[:16]
