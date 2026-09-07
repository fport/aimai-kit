"""Does the eval harness itself work?

The nastiest failure mode in eval code is silently returning 1.0: every
metric looks perfect because nothing was compared. These tests verify the
harness actually measures.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aimai_kit.prompts.cli import make_client, run_eval
from aimai_kit.prompts.registry import PromptRegistry
from aimai_kit.prompts.stub import StubExtractor

DATASET = Path("evals/golden_set/contracts.json")


@pytest.fixture(scope="module")
def result():
    return run_eval(
        StubExtractor(),
        DATASET,
        prompt_key="extract_contract@v2",
        schema_name="v2",
        registry=PromptRegistry("prompts"),
        limit=12,
    )


def test_golden_set_contains_edge_cases() -> None:
    raw = json.loads(DATASET.read_text(encoding="utf-8"))
    assert len(raw["records"]) >= 30
    edge_cases = {r["edge_case"] for r in raw["records"] if r["edge_case"]}
    assert len(edge_cases) >= 8


def test_metrics_are_produced(result) -> None:
    assert result.document_count == 12
    assert result.prompt_ref.startswith("extract_contract@v2+")
    assert result.prefix_signature
    assert result.schema_fingerprint
    assert 0.0 <= result.first_try_pass_rate <= 1.0
    assert result.mean_attempts >= 1.0
    assert result.input_tokens_p50 > 0


def test_field_accuracy_is_sorted_weakest_first(result) -> None:
    ratios = list(result.field_accuracy.values())
    assert ratios == sorted(ratios), "the weakest field must appear first"
    assert result.weakest_field == next(iter(result.field_accuracy))


def test_harness_actually_compares() -> None:
    """Catching a harness that always returns 'correct'.

    We run a stub that deliberately breaks everything; if accuracy still comes
    back at 1.0, the harness is not comparing anything.
    """

    class BrokenStub(StubExtractor):
        def _extract(self, document: str) -> dict:
            data = super()._extract(document)
            data["amount_minor"] = 1
            data["currency"] = "GBP"
            data["termination_notice_days"] = 9999
            return data

    result = run_eval(
        BrokenStub(corruption_rate=0.0, invalid_json_rate=0.0),
        DATASET,
        prompt_key="extract_contract@v2",
        registry=PromptRegistry("prompts"),
        limit=8,
    )
    assert result.field_accuracy["termination_notice_days"] == 0.0
    assert result.field_accuracy["currency"] < 0.5


def test_edge_case_failures_are_reported(result) -> None:
    """The stub's known weakness has to show up in the table."""
    assert "notice_in_months" in result.edge_case_failures


def test_stub_satisfies_the_client_protocol() -> None:
    from aimai_kit.provider.client import LLMClient

    assert isinstance(make_client("stub"), LLMClient)


def test_disabling_grounding_makes_v1_measurable() -> None:
    """v1 has no `citations` field, so grounding drops everything.

    That is a real finding about the schema — but it has to be separated out
    when comparing schema versions.
    """
    common = dict(
        dataset_path=DATASET,
        prompt_key="extract_contract@v1",
        schema_name="v1",
        registry=PromptRegistry("prompts"),
        limit=12,
    )
    with_drop = run_eval(StubExtractor(), **common, grounding_drop=True)
    without_drop = run_eval(StubExtractor(), **common, grounding_drop=False)
    assert with_drop.field_accuracy["start_date"] == 0.0
    assert without_drop.field_accuracy["start_date"] > 0.5


def test_pricing_model_projects_cost_onto_another_model() -> None:
    """The stub is free; this projects its token profile onto a real model."""
    from aimai_kit.provider.pricing import load_pricing

    result = run_eval(
        StubExtractor(),
        DATASET,
        prompt_key="extract_contract@v2",
        registry=PromptRegistry("prompts"),
        catalog=load_pricing("config/pricing.toml"),
        pricing_model="claude-opus-5",
        limit=6,
    )
    assert float(result.cost_per_doc_usd) > 0
    assert result.pricing_model == "claude-opus-5"
