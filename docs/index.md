---
hide:
  - navigation
---

<div class="aimai-hero" markdown>
![aimai-kit](assets/header.png)
</div>

<div class="aimai-badges" markdown>
[![PyPI](https://img.shields.io/pypi/v/aimai-kit?color=8FE64A&label=pypi)](https://pypi.org/project/aimai-kit/)
[![Python](https://img.shields.io/pypi/pyversions/aimai-kit?color=8FE64A)](https://pypi.org/project/aimai-kit/)
[![CI](https://github.com/fport/aimai-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/fport/aimai-kit/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-MIT-8FE64A)](https://github.com/fport/aimai-kit/blob/main/LICENSE)
</div>

# What this is

Five layers of LLM infrastructure, written without a framework, each built on
the one below it and each with its own measurements.

```bash
pip install "aimai-kit[providers]"
```

The point of the package is not that it does something no framework does. It
is that every decision in it is written down with the failure it prevents, and
every claim about it has a number behind it that you can reproduce without an
API key.

---

## The five layers

<div class="grid cards" markdown>

-   **[1. Provider](01-provider.md)**

    One internal message format, five error classes, four adapters. Retry is
    driven by the error *class*, never by matching message text.

    *The trap it closes:* Anthropic reports cached tokens outside
    `input_tokens`. Miss that and every Anthropic cost is silently low.

-   **[2. Prompts and context](02-prompts.md)**

    Versioned prompt files, a real context budget, structured output with a
    bounded repair loop, and citation verification.

    *The trap it closes:* putting the document in the system prompt
    invalidates the cache on every request. Nothing breaks — the bill just
    multiplies.

-   **[3. Tools](03-tools.md)**

    Schemas derived from function signatures, three provider exports, and an
    executor with five gates in front of it.

    *The trap it closes:* tenancy as a schema field means a model can claim to
    be another tenant.

-   **[4. Agent loop](04-agent.md)**

    Four budgets, one stop reason, graduated loop detection, and checkpoints
    that are just `to_dict` / `from_dict`.

    *The trap it closes:* an assistant turn with three tool calls and two
    results is a conversation most providers reject.

-   **[5. Harness](05-harness.md)**

    Segments, spill, threshold-triggered compaction, a memory store with a
    deterministic write gate, and sub-agents.

    *The trap it closes:* trimming from the middle invalidates every cached
    token after the cut. A 2,000-token saving can cost 40,000.

</div>

---

## Sixty seconds

=== "A call, measured"

    ```python
    from aimai_kit.provider.adapters import make_adapter
    from aimai_kit.provider.types import ChatRequest, Message, Role

    client = make_adapter("anthropic:claude-opus-5")
    result = client.complete(
        ChatRequest(
            messages=[Message(role=Role.USER, content="Say hello.")],
            system="Be brief.",
            max_output_tokens=64,
        )
    )
    print(result.text)
    print(result.usage.input_tokens, result.usage.cached_input_tokens)
    ```

=== "Extraction that cannot fabricate"

    ```python
    from aimai_kit.prompts import PromptRegistry, build_request, generate_structured
    from aimai_kit.prompts.grounding import verify_citations
    from aimai_kit.prompts.schemas import ContractSummary

    built = build_request(
        PromptRegistry("prompts"),
        "extract_contract@v2",
        document,
        schema=ContractSummary,
    )
    repaired = generate_structured(client, built.req, ContractSummary)
    summary, grounding = verify_citations(repaired.value, document)

    # Any field whose quote is not in the document has been set to None.
    print(summary.amount_minor, grounding.ratio, grounding.dropped)
    ```

=== "An agent with a budget"

    ```python
    from aimai_kit.agent import Agent, Budgets, Thread
    from aimai_kit.tools import CallContext, ToolExecutor
    from aimai_kit.tools.examples.orders import build_registry, seed_database

    seed_database()
    agent = Agent(
        client,
        ToolExecutor(build_registry()),
        budgets=Budgets(max_steps=8, max_seconds=60),
    )
    run = agent.run(
        Thread(),
        "What is the status of order 1002?",
        ctx=CallContext(user_id="u-1", tenant_id="t-1"),
    )
    print(run.stop_reason, run.answer)
    ```

---

## What the numbers say

Every figure is reproducible from the repository with no credentials. Full
tables and their caveats are in **[Measurements](measurements.md)**.

| Experiment | Finding |
|---|---|
| Schema v1 vs v2 | Grounding 0% → 100%, at 0.11 more attempts and 11% more cost per document |
| Grounding attribution | v1's `start_date` reads 0% with grounding on and 88.9% with it off |
| Tool descriptions | Cutting descriptions to one line leaves selection accuracy unchanged but raises forbidden-tool calls from 0% to 4.5% |
| Loop detection | p95 steps 7 → 3, at the cost of completion 100% → 75% |
| Harness configurations | Naive trim 101k tokens and no answer; compaction + a sub-agent, 12k and the answer survives |

!!! warning "The models behind these numbers are stubs"

    Not providers. They do real work — the extraction stub parses contracts
    with regexes, the selection stub scores queries against tool
    descriptions, the harness stub answers only from what is in its context —
    but they know the shape of the synthetic data, so their accuracy is
    optimistic.

    That is deliberate. These tables show that the measurement harness works
    and that the comparisons reproduce. For numbers about a model, run the
    same commands with `--model anthropic:claude-opus-5`.

---

## Before you ship any of this

The five chapters explain why each layer looks the way it does. The
**[production checklist](checklist.md)** turns that into something you can run
through before a release: what to check when you wire a provider, write a prompt,
add a tool, set a budget or let a run get long — every item tracing back to a
failure one of the chapters had to fix.
