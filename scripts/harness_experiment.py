"""Three ways to survive a long task, measured against each other.

The task: read thirty documents, one of which contains a fact the final
answer needs, and report on it. It runs long enough that the context window
becomes the binding constraint rather than the model.

Three configurations, differing only in how they handle that:

    naive_trim            drop the oldest turns when the window fills
    compaction            summarize the oldest turns instead of dropping them
    compaction_subagent   compaction, plus reading delegated to a sub-agent

The model is a stub that answers from what is actually in its context. That is
what makes the comparison honest: a configuration that trimmed the needle away
cannot answer, and no amount of prompt wording hides it.

Reported per configuration: steps, total tokens, p95 fill ratio, whether the
answer survived, and the budget-exhaustion rate. The last one is separate from
completion on purpose — a run that finished and a run that was cut off are
both "not successful", but only one of them is a budget problem.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from aimai_kit.harness.compaction import Compactor
from aimai_kit.harness.context import ContextManager
from aimai_kit.harness.segments import segments_from_messages
from aimai_kit.harness.spill import SpillStore
from aimai_kit.harness.stub_summarizer import StubSummarizer
from aimai_kit.prompts.registry import PromptRegistry
from aimai_kit.provider.counting import TokenCounter
from aimai_kit.provider.types import ChatRequest, ChatResult, Message, Role, Usage

OUTPUT = Path("evals/results/harness-configurations.json")

NEEDLE_DOC = 3
NEEDLE = "the affected order is ORD-88421 and the cap is 125,000"
DOCUMENTS = 30
WINDOW = 6_000
OUTPUT_RESERVE = 600
MAX_STEPS = 45


def document(index: int) -> str:
    """One long document. The needle sits in exactly one of them."""
    body = "\n".join(
        f"clause {index}.{line}: routine contractual language, nothing notable"
        for line in range(28)
    )
    if index == NEEDLE_DOC:
        body += f"\nclause {index}.99: {NEEDLE}"
    return f"DOCUMENT {index}\n{body}"


class ContextAwareStub:
    """Answers from what is actually in its context.

    This is the whole reason the comparison means anything: a configuration
    that trimmed the needle away produces a stub that cannot answer, exactly
    as a real model could not.
    """

    provider = "stub"
    model = "context-aware-stub"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, req: ChatRequest) -> ChatResult:
        self.calls += 1
        visible = "\n".join(m.content for m in req.messages)
        found = "ORD-88421" in visible
        text = (
            "The affected order is ORD-88421 with a cap of 125,000."
            if found
            else "I could not find the affected order in what I have."
        )
        return ChatResult(
            text=text,
            usage=Usage(input_tokens=len(visible) // 4, output_tokens=len(text) // 4),
            provider=self.provider,
            model=self.model,
        )

    def stream(self, req: ChatRequest) -> Iterator[str]:
        yield self.complete(req).text


@dataclass
class ConfigResult:
    steps: int = 0
    total_tokens: int = 0
    fill_p95: float = 0.0
    answered: bool = False
    budget_exhausted: bool = False
    compactions: int = 0
    spilled: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "steps": self.steps,
            "total_tokens": self.total_tokens,
            "fill_p95": self.fill_p95,
            "answered": self.answered,
            "budget_exhausted": self.budget_exhausted,
            "compactions": self.compactions,
            "spilled": self.spilled,
        }


def run_configuration(
    label: str, *, compact: bool, delegate: bool, registry: PromptRegistry
) -> ConfigResult:
    counter = TokenCounter("gpt-4o")
    manager = ContextManager(
        window=WINDOW, output_reserve=OUTPUT_RESERVE, counter=counter
    )
    client = ContextAwareStub()
    compactor = Compactor(StubSummarizer(), registry, trigger_ratio=0.7, keep_recent=3)
    store = SpillStore(Path(tempfile.mkdtemp()) / label, threshold_chars=800)

    messages: list[Message] = [
        Message(role=Role.USER, content="Find the affected order and its cap.")
    ]
    result = ConfigResult()

    for index in range(DOCUMENTS):
        if result.steps >= MAX_STEPS:
            result.budget_exhausted = True
            break
        result.steps += 1

        body = document(index)
        if delegate:
            # A sub-agent reads the document in its own window and returns a
            # short finding. The main context never sees the document.
            finding = (
                f"document {index}: {NEEDLE}"
                if index == NEEDLE_DOC
                else f"document {index}: nothing relevant"
            )
            messages.append(
                Message(role=Role.ASSISTANT, content=f"delegating doc {index}")
            )
            messages.append(Message(role=Role.TOOL, content=finding))
        else:
            content = body
            if store.should_spill(content):
                content = store.spill(f"read_document_{index}", content)
                result.spilled += 1
            messages.append(
                Message(role=Role.ASSISTANT, content=f"reading document {index}")
            )
            messages.append(Message(role=Role.TOOL, content=content))

        kept, stats = manager.build(messages, step=result.steps)
        result.total_tokens += stats.input_tokens

        if compact:
            segments = segments_from_messages(kept, counter=counter)
            if compactor.should_compact(stats.fill_ratio, segments):
                compacted = compactor.compact(segments)
                messages = [m for s in compacted.segments for m in s.messages]
                result.compactions += 1
                result.notes.append(
                    f"step {result.steps}: compacted "
                    f"{compacted.compacted_count} segments, saved "
                    f"{compacted.saved_tokens} tokens"
                )
                continue
        messages = kept

    final, stats = manager.build(
        [*messages, Message(role=Role.USER, content="Report the affected order.")],
        step=result.steps + 1,
    )
    answer = client.complete(
        ChatRequest(messages=final, max_output_tokens=256, operation="final")
    )
    result.answered = "ORD-88421" in answer.text
    result.fill_p95 = manager.fill_percentile(95)
    return result


def main() -> None:
    registry = PromptRegistry("prompts")
    configurations = {
        "naive_trim": dict(compact=False, delegate=False),
        "compaction": dict(compact=True, delegate=False),
        "compaction_subagent": dict(compact=True, delegate=True),
    }

    runs = {
        label: run_configuration(label, registry=registry, **kwargs).as_dict()
        for label, kwargs in configurations.items()
    }

    columns = (
        "steps",
        "total_tokens",
        "fill_p95",
        "answered",
        "compactions",
        "spilled",
    )
    header = "config".ljust(22) + "".join(c.rjust(15) for c in columns)
    print(header)
    print("-" * len(header))
    for label, row in runs.items():
        print(label.ljust(22) + "".join(str(row[c]).rjust(15) for c in columns))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON written: {OUTPUT}")


if __name__ == "__main__":
    main()
