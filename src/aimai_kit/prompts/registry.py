"""Moving prompts out of code into versioned files with fingerprints.

Why files: while a prompt is a Python string, a change shows up in the diff
as "one line changed", it becomes impossible to tell which run used which
text, and two versions cannot be measured side by side. The file + version +
fingerprint triple makes every eval row traceable back to the exact text that
produced it.

Why BOTH a version and a fingerprint: the version is for humans ("v2 is
better"), the fingerprint for machines. Version numbers are assigned by hand
and get forgotten — if someone edits `summarize@v2.md` without bumping the
version, the fingerprint still changes and two different texts cannot share
an identity in the eval records. Hence `name@vN+fingerprint`.

The fingerprint is taken from the RAW template, not the rendered text. The
render changes per call with its variables; what we want to measure is the
template itself.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, StrictUndefined, TemplateError

__all__ = [
    "HASH_LENGTH",
    "PromptRef",
    "PromptTemplate",
    "PromptRegistry",
    "fingerprint",
]

HASH_LENGTH = 8
NAME_VERSION_RE = re.compile(r"^(?P<name>[a-z0-9_]+)@(?P<version>v\d+)$")
FILE_RE = re.compile(r"^(?P<name>[a-z0-9_]+)@(?P<version>v\d+)\.md$")


def fingerprint(content: str) -> str:
    """Short sha256 of the raw template content.

    Line endings are normalized: if the same prompt saved with CRLF on
    Windows produced a different fingerprint, you would spend hours chasing
    "the prompt did not change but the measurement did".
    """
    normalized = content.replace("\r\n", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:HASH_LENGTH]


@dataclass(frozen=True, slots=True)
class PromptRef:
    """Identity of the prompt text a given run used."""

    name: str
    version: str
    fingerprint: str

    def __str__(self) -> str:
        return f"{self.name}@{self.version}+{self.fingerprint}"

    @property
    def name_version(self) -> str:
        return f"{self.name}@{self.version}"

    @classmethod
    def parse(cls, ref: str) -> PromptRef:
        head, _, fp = ref.partition("+")
        match = NAME_VERSION_RE.match(head)
        if not match:
            raise ValueError(
                f"Invalid prompt_ref: {ref!r}. Expected form: name@vN+fingerprint"
            )
        return cls(match["name"], match["version"], fp)


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    ref: PromptRef
    raw: str
    path: Path

    def render(self, **variables: object) -> str:
        return _environment().from_string(self.raw).render(**variables)


@lru_cache(maxsize=1)
def _environment() -> Environment:
    """`StrictUndefined` is REQUIRED.

    Jinja's default turns an undefined variable into an empty string. Write
    `{{ document }}` in a prompt, forget to pass it, and the model answers
    with an empty context — a result that gets filed as "the model
    hallucinated". In reality the prompt was empty. `StrictUndefined` catches
    that at runtime with a clear error.
    """
    return Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701


class PromptRegistry:
    """Loads and renders `name@vN.md` files from a directory."""

    def __init__(self, directory: str | Path = "prompts") -> None:
        self.directory = Path(directory)
        self._cache: dict[str, PromptTemplate] = {}

    # --- loading ----------------------------------------------------------

    def load(self, key: str) -> PromptTemplate:
        """Fetch a template by a key such as `summarize@v2`."""
        if key in self._cache:
            return self._cache[key]

        match = NAME_VERSION_RE.match(key)
        if not match:
            raise ValueError(f"Invalid prompt key: {key!r}. Expected: name@vN")
        path = self.directory / f"{key}.md"
        if not path.is_file():
            available = ", ".join(sorted(self.list_prompts())) or "(no prompts)"
            raise FileNotFoundError(f"Prompt not found: {path}. Available: {available}")
        raw = path.read_text(encoding="utf-8")
        template = PromptTemplate(
            ref=PromptRef(match["name"], match["version"], fingerprint(raw)),
            raw=raw,
            path=path,
        )
        self._cache[key] = template
        return template

    def list_prompts(self) -> list[str]:
        if not self.directory.is_dir():
            return []
        return [
            p.stem for p in sorted(self.directory.glob("*.md")) if FILE_RE.match(p.name)
        ]

    def versions(self, name: str) -> list[str]:
        """All versions of a prompt, in numeric order.

        Alphabetical sorting puts v10 before v2, so "the latest version" has
        to be resolved numerically.
        """
        found = [k for k in self.list_prompts() if k.startswith(f"{name}@")]
        return sorted(found, key=lambda k: int(k.split("@v")[1]))

    def latest(self, name: str) -> str:
        versions = self.versions(name)
        if not versions:
            raise FileNotFoundError(f"No versions exist for prompt '{name}'")
        return versions[-1]

    # --- rendering --------------------------------------------------------

    def render(self, key: str, **variables: object) -> tuple[str, PromptRef]:
        """Render the template and return which text produced it.

        Returning both is deliberate: a call path that takes the text and
        forgets the `prompt_ref` produces an unmeasurable run. With a single
        return value that mistake is easy to make.
        """
        template = self.load(key)
        try:
            return template.render(**variables), template.ref
        except TemplateError as error:
            raise ValueError(
                f"{template.path} failed to render: {error}. Make sure every "
                "template variable is passed (StrictUndefined is on)."
            ) from error
