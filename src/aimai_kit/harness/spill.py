"""Spill — large tool output goes to disk, a reference goes to the context.

Truncation in the tool layer stops a single result from filling the window.
It does not solve the underlying problem: the information is gone. An agent
that needed line 400 of a 900-line file now cannot get it, and it does not
know that it cannot.

Spilling keeps both properties. The full output is written to disk, the
context receives a short summary plus a `spill://` reference, and a tool lets
the agent read any range of the original when it actually needs it. Context
stays small, information stays reachable.

The summary is what makes this work. A reference with no summary forces the
agent to read the file to find out whether it is worth reading, which costs
the tokens the spill was supposed to save.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ["SpillStore", "SPILL_SCHEME", "spill_reference"]

SPILL_SCHEME = "spill://"
_REF_RE = re.compile(rf"{SPILL_SCHEME}([0-9a-f]{{12}})")


def spill_reference(spill_id: str) -> str:
    return f"{SPILL_SCHEME}{spill_id}"


@dataclass
class SpillStore:
    """Writes oversized tool output to disk under a per-run directory.

    Per-run directories rather than one shared folder: a run's spill files are
    garbage the moment the run ends, and a directory is easier to delete than
    a query.
    """

    root: Path
    threshold_chars: int = 4_000
    head_chars: int = 600

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def should_spill(self, content: str) -> bool:
        return len(content) > self.threshold_chars

    def spill(self, tool_name: str, content: str) -> str:
        """Write the content and return the summary that goes to the context."""
        spill_id = hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]
        path = self.root / f"{spill_id}.txt"
        path.write_text(content, encoding="utf-8")

        lines = content.count("\n") + 1
        head = content[: self.head_chars].rstrip()
        return (
            f"[{tool_name} returned {len(content)} characters over {lines} lines; "
            f"the full output is stored at {spill_reference(spill_id)}]\n\n"
            f"First {len(head)} characters:\n{head}\n\n"
            f"[use read_spill with ref={spill_reference(spill_id)} and a line "
            "range to read any part of the full output]"
        )

    def read(self, ref: str, start_line: int = 1, end_line: int = 200) -> str:
        """Read a line range out of a spilled file."""
        match = _REF_RE.search(ref)
        if match is None:
            return f"'{ref}' is not a valid spill reference."
        path = self.root / f"{match.group(1)}.txt"
        if not path.is_file():
            return f"No stored output for {ref}; it may belong to another run."

        lines = path.read_text(encoding="utf-8").splitlines()
        start = max(1, start_line)
        end = min(len(lines), max(start, end_line))
        body = "\n".join(lines[start - 1 : end])
        return f"[lines {start}-{end} of {len(lines)} from {ref}]\n{body}"

    def clear(self) -> None:
        for path in self.root.glob("*.txt"):
            path.unlink()


def build_spill_tools(store: SpillStore):
    """Two tools: read a spilled result, and use a scratchpad.

    The scratchpad is the other half of the same idea. An agent working
    through thirty documents needs somewhere to put intermediate findings that
    is not the context window; a file it can write to and read back is the
    smallest thing that works.
    """
    from ..tools.decorator import tool

    scratchpad = store.root / "scratchpad.md"

    @tool
    def read_spill(ref: str, start_line: int = 1, end_line: int = 200) -> str:
        """Read part of a large tool output that was stored outside the context.

        Use this when a previous tool result said its full output is at a
        spill:// reference. To re-run the original query instead, use the tool
        that produced it.
        """
        return store.read(ref, start_line, end_line)

    @tool
    def write_note(text: str) -> str:
        """Append a finding to the scratchpad for later.

        Use this for intermediate results you will need after many more steps.
        To read them back, use read_notes.
        """
        with scratchpad.open("a", encoding="utf-8") as handle:
            handle.write(text.rstrip() + "\n")
        return f"noted ({len(text)} characters)"

    @tool
    def read_notes() -> str:
        """Read everything written to the scratchpad so far.

        To add a new finding, use write_note.
        """
        if not scratchpad.is_file():
            return "The scratchpad is empty."
        return scratchpad.read_text(encoding="utf-8")

    return [read_spill, write_note, read_notes]
