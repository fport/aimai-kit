"""Sub-agents: constrained reports and verified evidence."""

from __future__ import annotations

import json

import pytest

from aimai_kit.agent import Budgets, ScriptedClient
from aimai_kit.harness.subagent import Subagent, SubagentReport
from aimai_kit.provider.types import ChatRequest, ChatResult, Usage
from aimai_kit.tools import ToolExecutor, ToolRegistry, tool


@tool
def read_source(source_id: str) -> str:
    """Read one source document.

    To list sources, use another tool.
    """
    return f"source {source_id}: the affected order is ORD-88421"


class ReportingClient(ScriptedClient):
    """A scripted client that also answers the schema-bound report call."""

    def __init__(self, script, report: dict) -> None:
        super().__init__(script)
        self._report = report

    def complete(self, req: ChatRequest) -> ChatResult:
        if req.operation == "subagent_report":
            self.requests.append(req)
            return ChatResult(
                text=json.dumps(self._report),
                usage=Usage(input_tokens=200, output_tokens=60),
                provider=self.provider,
                model=self.model,
            )
        return super().complete(req)


@pytest.fixture
def executor() -> ToolExecutor:
    return ToolExecutor(ToolRegistry([read_source]))


def _subagent(executor, script, report) -> Subagent:
    return Subagent(
        client=ReportingClient(script, report),
        executor=executor,
        allowlist=["read_source"],
        budgets=Budgets(max_steps=6, max_seconds=None),
    )


def test_report_is_schema_constrained(executor) -> None:
    """The caller gets something to use, not prose to interpret."""
    agent = _subagent(
        executor,
        [[("read_source", '{"source_id": "s-1"}')], "found the order"],
        {
            "summary": "The affected order is ORD-88421.",
            "evidence": ["ORD-88421"],
            "confident": True,
        },
    )
    result = agent.run("Which order is affected?")
    assert isinstance(result.report, SubagentReport)
    assert result.report.summary


def test_evidence_present_in_the_transcript_is_kept(executor) -> None:
    agent = _subagent(
        executor,
        [[("read_source", '{"source_id": "s-1"}')], "found it"],
        {"summary": "Found ORD-88421.", "evidence": ["ORD-88421"], "confident": True},
    )
    result = agent.run("Which order is affected?")
    assert result.verified_evidence == ["ORD-88421"]
    assert result.report.confident is True


def test_invented_evidence_is_dropped_and_confidence_lowered(executor) -> None:
    """A citation nobody can resolve is worse than admitting nothing was found."""
    agent = _subagent(
        executor,
        [[("read_source", '{"source_id": "s-1"}')], "found it"],
        {
            "summary": "Found two orders.",
            "evidence": ["ORD-88421", "ORD-00000"],
            "confident": True,
        },
    )
    result = agent.run("Which orders are affected?")
    assert result.unverified_evidence == ["ORD-00000"]
    assert result.report.evidence == ["ORD-88421"]
    assert result.report.confident is False


def test_empty_evidence_is_a_valid_answer(executor) -> None:
    agent = _subagent(
        executor,
        ["nothing found"],
        {"summary": "No relevant orders.", "evidence": [], "confident": True},
    )
    result = agent.run("Which orders are affected?")
    assert result.report.evidence == []
    assert result.report.confident is True


def test_compression_ratio_is_measured(executor) -> None:
    """A sub-agent that returns what it read has not delegated anything."""
    agent = _subagent(
        executor,
        [[("read_source", f'{{"source_id": "s-{i}"}}')] for i in range(4)] + ["done"],
        {"summary": "Short answer.", "evidence": [], "confident": True},
    )
    result = agent.run("Read the sources.")
    assert result.tokens_spent > result.tokens_returned
    assert result.compression_ratio > 1.0


def test_subagent_runs_in_its_own_thread(executor) -> None:
    """The main context never sees the documents the sub-agent read."""
    agent = _subagent(
        executor,
        [[("read_source", '{"source_id": "s-1"}')], "found it"],
        {"summary": "Found ORD-88421.", "evidence": ["ORD-88421"], "confident": True},
    )
    result = agent.run("Which order?")
    assert "source s-1:" not in result.report.summary


def test_allowlist_narrows_the_subagent(executor) -> None:
    @tool
    def dangerous(x: str) -> str:
        """Do something the sub-agent must not do."""
        return x

    ex = ToolExecutor(ToolRegistry([read_source, dangerous]))
    agent = Subagent(
        client=ReportingClient(
            ["done"], {"summary": "Nothing.", "evidence": [], "confident": True}
        ),
        executor=ex,
        allowlist=["read_source"],
    )
    agent.run("task")
    declared = {t["name"] for t in agent.client.requests[0].tools}
    assert declared == {"read_source"}
