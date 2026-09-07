"""Citation verification: passing the schema does not make output correct."""

from __future__ import annotations

from aimai_kit.prompts.grounding import normalize, verify_citations
from aimai_kit.prompts.schemas import ContractSummary

DOCUMENT = (
    "SERVICES AGREEMENT\n"
    "This Agreement shall commence on March 1, 2025 and shall expire on "
    "February 28, 2026.\n"
    "The service fee is USD 45,000 per month exclusive of tax.\n"
    "Either party may terminate on thirty (30) days' prior written notice."
)


def _summary(**overrides) -> ContractSummary:
    base = dict(
        start_date="2025-03-01",
        end_date="2026-02-28",
        amount_minor=4_500_000,
        currency="USD",
        termination_notice_days=30,
    )
    return ContractSummary(**{**base, **overrides})


def test_valid_citations_keep_the_fields() -> None:
    summary = _summary(
        citations={
            "start_date": "This Agreement shall commence on March 1, 2025",
            "end_date": "shall expire on February 28, 2026",
            "amount_minor": "The service fee is USD 45,000 per month",
            "termination_notice_days": "thirty (30) days' prior written notice",
        }
    )
    cleaned, report = verify_citations(summary, DOCUMENT)
    assert report.ratio == 1.0
    assert not report.dropped
    assert cleaned.amount_minor == 4_500_000


def test_fabricated_citation_drops_the_field() -> None:
    """Output that passes the schema but is ungrounded: the real danger."""
    summary = _summary(
        amount_minor=99_900_000,
        citations={"amount_minor": "The agreed fee is USD 999,000 per month"},
    )
    cleaned, report = verify_citations(summary, DOCUMENT)
    assert cleaned.amount_minor is None
    assert "amount_minor" in report.dropped
    assert any(s.status == "citation_not_found" for s in report.statuses)


def test_filled_field_without_a_citation_is_dropped() -> None:
    summary = _summary(citations={})
    cleaned, report = verify_citations(summary, DOCUMENT)
    assert cleaned.amount_minor is None and cleaned.start_date is None
    assert len(report.dropped) == 4


def test_empty_fields_do_not_hurt_the_ratio() -> None:
    """A field the model correctly left null must not be punished."""
    _, report = verify_citations(ContractSummary(), DOCUMENT)
    assert report.ratio == 1.0
    assert all(s.status == "empty" for s in report.statuses)


def test_whitespace_and_quote_differences_still_match() -> None:
    summary = _summary(
        citations={"amount_minor": "The service   fee\nis USD 45,000   per month"}
    )
    _, report = verify_citations(summary, DOCUMENT)
    status = next(s for s in report.statuses if s.field == "amount_minor")
    assert status.status == "grounded"


def test_paraphrase_is_caught() -> None:
    """Normalization loosens matching but does not make it free-form."""
    summary = _summary(
        citations={"amount_minor": "the monthly charge was set at forty five thousand"}
    )
    cleaned, _ = verify_citations(summary, DOCUMENT)
    assert cleaned.amount_minor is None


def test_too_short_citation_is_rejected() -> None:
    """'2025' appears in almost every document; it verifies nothing."""
    summary = _summary(citations={"start_date": "2025"})
    cleaned, _ = verify_citations(summary, DOCUMENT)
    assert cleaned.start_date is None


def test_drop_can_be_disabled_for_reporting_only() -> None:
    summary = _summary(citations={})
    same, report = verify_citations(summary, DOCUMENT, drop=False)
    assert same.amount_minor == 4_500_000
    assert report.ratio == 0.0


def test_normalize_handles_case_and_smart_quotes() -> None:
    assert normalize("  The   “Agreement”  ") == normalize('the "agreement"')
