"""A stub extractor so the eval harness runs without an API key.

Why a test double ships inside the package: the eval harness is itself code,
and claiming "I wrote an eval" without demonstrating that it runs is an
unmeasured claim. This class satisfies `LLMClient`, performs real extraction
(regex-based) and produces a realistic error distribution. That gives us:

- an eval test that runs in CI with no credentials,
- metric computation (field accuracy, repair rate, grounding) verified
  against MEANINGFUL numbers rather than zeros,
- and results that are clearly marked as belonging to a stub, not a model
  (`provider="stub"`).

THIS IS NOT A MODEL. The real measurement table is produced by running with
`--model anthropic:claude-opus-5` and your own key. The stub only proves the
harness measures correctly.

It is deliberately weak: it cannot read a notice period written in months, an
amount given inclusive of tax, or a date outside its format. Those weaknesses
line up with the edge cases in the golden set, so "weakest field" in the eval
table really is the weakest field.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from datetime import datetime

from ..provider.types import ChatRequest, ChatResult, Role, Usage

__all__ = ["StubExtractor"]

_DATE_RE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")
_AMOUNT_RE = re.compile(r"\b(USD|EUR|GBP|TRY)\s+([\d,]+(?:\.\d{2})?)")
_NOTICE_RE = re.compile(r"\((\d+)\)\s*days'?\s+prior written notice")
_PARTY_RE = re.compile(
    r"([A-Z][\w&.\- ]{2,60}?(?:Ltd\.|Inc\.|plc|GmbH|AB|LLC))\s*\(the"
)
_FORUM_RE = re.compile(r"the courts of ([A-Z][A-Za-z ]+?)\.")


def _span_around(text: str, position: int, width: int = 120) -> str:
    """Return the text around a match, to be used as a citation."""
    start = max(0, position - width // 3)
    return " ".join(text[start : position + width].split())


class StubExtractor:
    """Regex-based contract field extractor conforming to `LLMClient`."""

    provider = "stub"

    def __init__(
        self,
        model: str = "stub-regex-v1",
        *,
        corruption_rate: float = 0.15,
        invalid_json_rate: float = 0.10,
    ) -> None:
        self.model = model
        self.corruption_rate = corruption_rate
        self.invalid_json_rate = invalid_json_rate
        self._seen: dict[str, int] = {}

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _document_of(req: ChatRequest) -> str:
        """The FIRST user message — the document lives there.

        Taking the LAST user message was wrong: during a repair round that
        message is the repair instruction, not the document, so the stub
        extracted from the instruction and always returned an empty object. A
        real model does not fall into this trap because it sees the whole
        conversation; a test double has a contract too.
        """
        for m in req.messages:
            if m.role is Role.USER:
                return m.content
        return ""

    @staticmethod
    def _dice(seed: str) -> float:
        """Deterministic 'randomness' derived from the document.

        With real randomness two eval runs would produce different numbers
        and the question "is v1 or v2 better?" would drown in noise.
        """
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) / 0xFFFFFFFF

    def _extract(self, document: str) -> dict:
        data: dict = {
            "parties": [],
            "start_date": None,
            "end_date": None,
            "amount_minor": None,
            "currency": None,
            "termination_notice_days": None,
            "auto_renewal": None,
            "jurisdiction": None,
            "risk_level": "medium",
            "risk_rationale": None,
            "citations": {},
        }

        parties = list(dict.fromkeys(_PARTY_RE.findall(document)))[:2]
        data["parties"] = [p.strip() for p in parties]

        for match in _DATE_RE.finditer(document):
            iso = datetime.strptime(match.group(1), "%B %d, %Y").date().isoformat()
            head = document[max(0, match.start() - 90) : match.start()]
            if data["start_date"] is None and (
                "commence on" in head or "take effect on" in head
            ):
                data["start_date"] = iso
                data["citations"]["start_date"] = _span_around(document, match.start())
            elif data["end_date"] is None and "expire on" in head:
                data["end_date"] = iso
                data["citations"]["end_date"] = _span_around(document, match.start())

        amount = _AMOUNT_RE.search(document)
        if amount:
            digits = amount.group(2).replace(",", "")
            minor = round(float(digits) * 100)
            data["amount_minor"] = minor
            data["currency"] = amount.group(1)
            data["citations"]["amount_minor"] = _span_around(document, amount.start())

        notice = _NOTICE_RE.search(document)
        if notice:
            data["termination_notice_days"] = int(notice.group(1))
            data["citations"]["termination_notice_days"] = _span_around(
                document, notice.start()
            )

        forum = _FORUM_RE.search(document)
        if forum:
            data["jurisdiction"] = f"the courts of {forum.group(1).strip()}"

        if "renew automatically" in document:
            data["auto_renewal"] = True

        # `or` binds looser than `and`; keeping the two signals as separate
        # membership checks avoids the precedence trap.
        has_penalty = "penalty of" in document
        has_unlimited = "liability" in document and "unlimited" in document
        if has_penalty or has_unlimited:
            data["risk_level"] = "high"
            data["risk_rationale"] = (
                "Unilateral termination without cause, a 50% penalty clause "
                "and unlimited supplier liability all operate against the "
                "Supplier."
            )
        return data

    # --- LLMClient protocol -----------------------------------------------

    def complete(self, req: ChatRequest) -> ChatResult:
        document = self._document_of(req)
        key = hashlib.sha256(document.encode("utf-8")).hexdigest()[:12]
        attempt = self._seen.get(key, 0)
        self._seen[key] = attempt + 1

        data = self._extract(document)
        roll = self._dice(key)

        # Deliberate corruption on the first attempt, fixed on the repair
        # round. It mimics real model behavior: once the error list goes back,
        # the second attempt usually lands.
        if attempt == 0:
            if roll < self.invalid_json_rate:
                return self._result("```json\n{ broken json, field: none\n```", req)
            if roll < self.invalid_json_rate + self.corruption_rate:
                # Cross-field violation: end before start.
                if data["start_date"] and data["end_date"]:
                    data["end_date"], data["start_date"] = (
                        data["start_date"],
                        data["end_date"],
                    )
                else:
                    data["risk_level"] = "high"
                    data["risk_rationale"] = None  # rationale requirement broken

        return self._result(json.dumps(data, ensure_ascii=False), req)

    def _result(self, text: str, req: ChatRequest) -> ChatResult:
        return ChatResult(
            text=text,
            usage=Usage(
                input_tokens=len(self._document_of(req)) // 4,
                output_tokens=len(text) // 4,
            ),
            provider=self.provider,
            model=self.model,
            prompt_ref=req.prompt_ref,
        )

    def stream(self, req: ChatRequest) -> Iterator[str]:
        yield self.complete(req).text
