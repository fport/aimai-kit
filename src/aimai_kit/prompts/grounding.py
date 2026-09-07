"""Citation verification — passing the schema does not make output correct.

`amount_minor: 125000` fits the schema perfectly and that figure may appear
nowhere in the document. A schema validates SHAPE, not CONTENT.

The fix is to require a VERBATIM quote from the document for every critical
field, then verify PROGRAMMATICALLY that the quote really occurs in the
source. We do not trust the model's claim about its source; we look for what
it claims in the text.

When the quote cannot be found, the field is dropped to `None` — not
silently: the report line says which field was dropped and why. "I don't
know" beats an ungrounded number, especially in a contract summary.

Why normalization is needed: models change whitespace, line breaks and quote
characters while copying. A raw `in` check would reject most correct
citations. Normalization loosens the match but does not make it free-form —
paraphrases are still caught.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from pydantic import BaseModel

from .schemas import CRITICAL_FIELDS

__all__ = [
    "MIN_CITATION_LENGTH",
    "FieldStatus",
    "GroundingReport",
    "normalize",
    "verify_citations",
]

_WHITESPACE_RE = re.compile(r"\s+")
# Characters models routinely substitute while copying; all are folded to
# their plain equivalents before matching.
_PUNCT_MAP = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})

MIN_CITATION_LENGTH = 12


def normalize(text: str) -> str:
    """Flatten text for matching.

    NFKC normalizes composed characters; `casefold` handles case. Neither is
    perfect for every locale, but both are sufficient for citation matching
    and, unlike locale-dependent conversion, portable.
    """
    text = unicodedata.normalize("NFKC", text).translate(_PUNCT_MAP)
    return _WHITESPACE_RE.sub(" ", text).strip().casefold()


@dataclass(frozen=True, slots=True)
class FieldStatus:
    field: str
    status: str  # "grounded" | "no_citation" | "citation_not_found" | "empty"
    citation: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("grounded", "empty")


@dataclass(frozen=True, slots=True)
class GroundingReport:
    statuses: list[FieldStatus] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        """Share of populated critical fields whose citation was verified.

        Empty fields stay out of the denominator: counting a field the model
        correctly left null as "not grounded" would punish the right behavior
        and make the ratio meaningless.
        """
        relevant = [s for s in self.statuses if s.status != "empty"]
        if not relevant:
            return 1.0
        return sum(s.status == "grounded" for s in relevant) / len(relevant)

    def lines(self) -> list[str]:
        return [
            f"{s.field}: {s.status}"
            + (f" -> {s.citation[:60]!r}" if s.citation else "")
            for s in self.statuses
        ]


def _citation_found(citation: str, normalized_source: str) -> bool:
    """Does the quote occur in the source?

    Very short quotes are rejected: a fragment like "2025" appears in almost
    every document and makes verification meaningless. The threshold is high
    enough to filter coincidental matches and low enough not to cut real
    quotes.
    """
    normalized = normalize(citation)
    if len(normalized) < MIN_CITATION_LENGTH:
        return False
    return normalized in normalized_source


def verify_citations[T: BaseModel](
    obj: T,
    source_text: str,
    *,
    critical_fields: tuple[str, ...] = CRITICAL_FIELDS,
    drop: bool = True,
) -> tuple[T, GroundingReport]:
    """Verify citations for the critical fields; null out what fails.

    `drop=False` produces the report without modifying the object — useful in
    an eval run to measure "how much was grounded before we corrected
    anything".
    """
    citations: dict[str, str] = getattr(obj, "citations", {}) or {}
    normalized_source = normalize(source_text)

    statuses: list[FieldStatus] = []
    to_drop: dict[str, None] = {}

    for name in critical_fields:
        value = getattr(obj, name, None)
        if value is None:
            statuses.append(FieldStatus(name, "empty"))
            continue

        citation = (citations.get(name) or "").strip()
        if not citation:
            statuses.append(FieldStatus(name, "no_citation"))
            to_drop[name] = None
            continue

        if _citation_found(citation, normalized_source):
            statuses.append(FieldStatus(name, "grounded", citation))
        else:
            statuses.append(FieldStatus(name, "citation_not_found", citation))
            to_drop[name] = None

    report = GroundingReport(statuses=statuses, dropped=list(to_drop))
    if not drop or not to_drop:
        return obj, report

    # Re-validate rather than `model_copy`: dropping a field can affect the
    # cross-field rules (amount_minor requiring currency, for instance) and we
    # do not want to hand back a quietly invalid object.
    data = obj.model_dump()
    data.update(to_drop)
    return type(obj).model_validate(data), report
