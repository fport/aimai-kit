"""Output schemas — how schema design shapes output quality.

Two versions live here on purpose: `ContractSummaryV1` is the naive first
design, `ContractSummary` (v2) is what it became after labeling a golden set
and running into edge cases. The field-accuracy table in the docs compares
the two.

Four things changed between v1 and v2, each for a reason:

1. `risk_level` was a free-form string -> now a `Literal`. With free text the
   model produced "medium-high", "MEDIUM" and "risky"; none were wrong and
   none were comparable. An enum is the only thing that makes per-field
   accuracy measurable.

2. `amount` was a float -> now `amount_minor`, an int. As a float
   "1,250,000.50" sometimes arrived as 1250000.5 and sometimes as 1250.0005
   depending on how the thousands separator was read. Minor units as an
   integer closes both that ambiguity and non-Decimal arithmetic.

3. `description` texts were added. The field name is not the only signal the
   model gets; writing "the end date stated in the contract text, NOT a date
   extended by auto-renewal" on `end_date` produced a visible improvement on
   the worst-performing field.

4. `citations` was added. Output that passes schema validation can still be
   WRONG — that is the central lesson of the output side. A citation field
   leaves a hook that can be verified programmatically.

The schema is kept SHALLOW: two levels at most. A deeper schema would be
better served by splitting into two calls; with deep schemas models quietly
leave nested objects empty.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "RiskLevel",
    "Currency",
    "ContractSummaryV1",
    "ContractSummary",
    "CRITICAL_FIELDS",
    "strict_json_schema",
]


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


Currency = Literal["USD", "EUR", "GBP", "TRY"]

# Fields that citation verification treats as mandatory. The criterion is
# concrete: these are the fields where being wrong has a financial or legal
# consequence. Party names matter too, but they are free text and citation
# matching on them is noisy, so they are left out.
CRITICAL_FIELDS = (
    "start_date",
    "end_date",
    "amount_minor",
    "termination_notice_days",
)


class ContractSummaryV1(BaseModel):
    """The first design. Kept for comparison; do not use in new code."""

    parties: list[str] = Field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None
    amount: float | None = None
    currency: str | None = None
    termination_notice_days: int | None = None
    risk_level: str | None = None
    summary: str = ""


class ContractSummary(BaseModel):
    """Structured summary extracted from a contract (v2).

    Every `description` is text THE MODEL READS; do not rely on the field
    name alone. These sentences answer real confusions that surfaced while
    labeling the golden set.
    """

    parties: list[str] = Field(
        default_factory=list,
        description=(
            "Full legal names of the signing parties, exactly as they appear "
            "in the document. Not abbreviations or role labels like 'Client'."
        ),
    )
    start_date: date | None = Field(
        default=None,
        description=(
            "The date the agreement takes effect, YYYY-MM-DD. If the signing "
            "date differs from the effective date, use the EFFECTIVE date. "
            "Null when not stated."
        ),
    )
    end_date: date | None = Field(
        default=None,
        description=(
            "The end date stated in the contract text, YYYY-MM-DD. Do NOT "
            "compute a date extended by auto-renewal; take what is written. "
            "Null for an open-ended agreement."
        ),
    )
    amount_minor: int | None = Field(
        default=None,
        description=(
            "Total contract value in MINOR UNITS as an integer (1,250.50 -> "
            "125050). If a tax-exclusive figure is given, use it. For a "
            "recurring fee, record the PERIODIC amount, not an annualized "
            "total. Null when not stated."
        ),
    )
    currency: Currency | None = Field(
        default=None,
        description="Currency of the amount. Required when amount_minor is set.",
    )
    termination_notice_days: int | None = Field(
        default=None,
        description=(
            "How many days of prior written notice termination requires. "
            "Convert months to days (1 month = 30 days). Null when not stated."
        ),
    )
    auto_renewal: bool | None = Field(
        default=None,
        description=(
            "Whether the agreement renews automatically at the end of its "
            "term. Null when the document does not say; do not write false "
            "because it 'probably' does not."
        ),
    )
    jurisdiction: str | None = Field(
        default=None,
        description="Courts or forum named for disputes. Null when absent.",
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.MEDIUM,
        description=(
            "Risk level against the supplier. 'high' means unilateral "
            "termination, unlimited liability or a penalty clause is present. "
            "'low' means mutual and capped liability. Use 'medium' when "
            "unsure."
        ),
    )
    risk_rationale: str | None = Field(
        default=None,
        description=(
            "REQUIRED when risk_level is 'high': name in one sentence which "
            "clause creates the risk. Optional otherwise."
        ),
    )
    citations: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Source quotes for the critical fields: key is the field name, "
            "value is a span copied VERBATIM from the document, at most 200 "
            "characters. Do not paraphrase or summarize; copy. Expected for: "
            + ", ".join(CRITICAL_FIELDS)
        ),
    )

    # --- cross-field rules ------------------------------------------------

    @model_validator(mode="after")
    def _end_after_start(self) -> ContractSummary:
        """Catches the case where each field is valid but the pair is not.

        Both dates can be valid ISO 8601 and the object can still describe an
        impossible fact. Per-field validation cannot see that; a cross-field
        rule can.
        """
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError(
                f"end_date ({self.end_date}) cannot precede start_date "
                f"({self.start_date})"
            )
        return self

    @model_validator(mode="after")
    def _high_risk_needs_rationale(self) -> ContractSummary:
        """A claim needs a basis.

        Not only data integrity but a PRODUCT decision: an unexplained "high
        risk" flag warns the user without telling them what to do, and gets
        ignored over time.
        """
        if (
            self.risk_level is RiskLevel.HIGH
            and not (self.risk_rationale or "").strip()
        ):
            raise ValueError("risk_rationale is required when risk_level is 'high'")
        return self

    @model_validator(mode="after")
    def _amount_needs_currency(self) -> ContractSummary:
        """An amount without a unit is a number, not money."""
        if self.amount_minor is not None and self.currency is None:
            raise ValueError("currency is required when amount_minor is set")
        return self


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Adapt a Pydantic schema to the providers' strict mode.

    Three transformations, each a real cause of rejection:

    - `additionalProperties: false` on every object. Without it the model can
      invent fields that are not in the schema and validation still passes.
    - Every field becomes `required`. Strict mode has no notion of an
      optional field; optionality is expressed as `anyOf: [type, null]`,
      which Pydantic already produces. Making a field required forces the
      model to write `null` explicitly rather than OMIT it — and those are
      not the same thing: the first means "I forgot", the second means "the
      document does not say".
    - `format`, `default` and `title` are stripped; strict mode rejects
      keywords outside its vocabulary. The information they carried is
      already in `description` (e.g. "YYYY-MM-DD" on the date fields).
    """

    def clean(node: Any) -> Any:
        if isinstance(node, dict):
            out = {
                k: clean(v)
                for k, v in node.items()
                if k not in ("format", "default", "title")
            }
            if out.get("type") == "object" and "properties" in out:
                out["additionalProperties"] = False
                out["required"] = list(out["properties"].keys())
            return out
        if isinstance(node, list):
            return [clean(x) for x in node]
        return node

    return clean(model.model_json_schema())
