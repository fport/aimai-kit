"""Three layers of isolation, and which one actually matters.

Tools run code. Code that came from a model, acting on arguments that came
from a document, which may have come from anywhere. The isolation story has
three layers and they are not equally important:

    1. in-process   binary allowlist and a path jail (this file)
    2. process      timeout and a cleaned environment (this file)
    3. container    no network, resource limits (deployment, not code)

Layer 3 is the one that matters, and closing the network is the single most
important decision in it. Layers 1 and 2 stop mistakes; a process with no
route out cannot exfiltrate anything even when layers 1 and 2 are defeated,
because there is nowhere to send it. Every other control degrades gracefully.
Network access does not: it is on or off.

This file implements what can be implemented in-process, and is explicit
about the fact that it is the weakest of the three.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["SandboxViolation", "Sandbox"]

# Environment variables that must never reach a subprocess. Passing the parent
# environment through is the most common way a credential ends up in a tool's
# reach.
_ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "TZ", "HOME")


class SandboxViolation(Exception):
    """The call was refused before anything ran."""


@dataclass
class Sandbox:
    """A path jail and a binary allowlist for tools that touch the system."""

    root: Path
    allowed_binaries: frozenset[str] = field(
        default_factory=lambda: frozenset({"ls", "cat", "grep", "wc", "head", "tail"})
    )
    timeout_s: float = 10.0

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, relative: str) -> Path:
        """Resolve a path inside the jail, or refuse.

        `Path.resolve()` before the check, not after: without it `../../etc`
        passes a string comparison and then escapes. Symlinks are resolved by
        the same call, which closes the other obvious route out.
        """
        candidate = (self.root / relative).resolve()
        if not candidate.is_relative_to(self.root):
            raise SandboxViolation(
                f"path {relative!r} resolves outside the sandbox root"
            )
        return candidate

    def run(self, command: str, *, cwd: str = ".") -> subprocess.CompletedProcess:
        """Run an allowlisted command inside the jail.

        Not `shell=True`. A shell turns one command into a language with
        pipes, substitution and redirection, and an allowlist over a language
        is not an allowlist.
        """
        parts = shlex.split(command)
        if not parts:
            raise SandboxViolation("empty command")
        binary = Path(parts[0]).name
        if binary not in self.allowed_binaries:
            raise SandboxViolation(
                f"{binary!r} is not on the allowlist "
                f"({', '.join(sorted(self.allowed_binaries))})"
            )

        working = self.resolve(cwd)
        environment = {k: os.environ[k] for k in _ENV_ALLOWLIST if k in os.environ}

        return subprocess.run(  # noqa: S603 - allowlisted binary, no shell
            parts,
            cwd=working,
            env=environment,
            capture_output=True,
            text=True,
            timeout=self.timeout_s,
            check=False,
        )
