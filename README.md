# aimai-kit

A framework-free LLM engineering toolkit in one Python package.

| Layer | Package | What it adds |
|---|---|---|
| 1 | `provider/` | Token/cost/latency measurement, four adapters, retry and fallback |
| 2 | `prompts/` | Versioned prompts, context budget, structured output, a repair loop |
| 3 | `tools/` | Schemas from signatures, three provider exports, a five-gate executor |

Later layers (agent, harness) build on these.

No vendor SDK outside `provider/adapters/`, and every layer runs
without an API key.

## Install

```bash
uv sync --all-extras --group dev
cp .env.example .env     # add your keys
uv run pytest            # live tests excluded
```

## Quick start

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
print(result.text, result.usage.input_tokens, result.usage.output_tokens)
```

Structured extraction with citation verification:

```python
from aimai_kit.prompts import PromptRegistry, build_request, generate_structured
from aimai_kit.prompts.grounding import verify_citations
from aimai_kit.prompts.schemas import ContractSummary

built = build_request(
    PromptRegistry("prompts"), "extract_contract@v2", document, schema=ContractSummary
)
repaired = generate_structured(client, built.req, ContractSummary)
summary, grounding = verify_citations(repaired.value, document)
print(summary.amount_minor, grounding.ratio)   # ungrounded fields are dropped
```

A safe tool call:

```python
from aimai_kit.tools import CallContext, ToolExecutor
from aimai_kit.tools.examples.orders import build_registry, seed_database

seed_database()
executor = ToolExecutor(build_registry())
result = executor.call(
    "get_order", '{"order_id": "1002"}', CallContext(user_id="u-1", tenant_id="t-1")
)
print(result.ok, result.content)
```

```bash
# Compare models: TTFT from streaming, real usage from one complete call
uv run model-probe --prompt evals/probe/sample-prompt.txt \
  --models anthropic:claude-opus-5 anthropic:claude-haiku-4-5 -n 5
```

---

## Why each layer looks the way it does

Short version below; the full reasoning, including what was rejected and why,
is in `docs/`.

**[Provider](docs/01-provider.md)** — one internal message format and five
error classes. Retry decisions are driven by the error *class*, never by
matching message text. Cached tokens are normalized to a single rule across
providers, because Anthropic reports them outside `input_tokens` and every
cost calculation downstream depends on which convention you picked.

**[Prompts and context](docs/02-prompts.md)** — prompts are versioned files
identified as `name@vN+fingerprint`. The document goes into a user message,
never the system block, so the cache prefix stays byte-identical across
requests. Trimming is an explicit decision that produces a report line, and
the non-trimmable sections raise rather than shrink.

**[Tools](docs/03-tools.md)** — the schema is derived from the function
signature, so the two cannot drift apart. Five gates run before anything
executes, each producing a message the model can act on. Server context
(`tenant_id`) is injected from the call and is absent from the schema, so a
model cannot claim to be another tenant.

---

## Measurements

Every number below is reproducible from this repository with no credentials.
Full tables and the caveats are in **[docs/measurements.md](docs/measurements.md)**.

| Experiment | Finding |
|---|---|
| Schema v1 vs v2 | Grounding 0% -> 100%, at 0.11 more attempts and 11% more cost per document |
| Grounding attribution | v1's `start_date` reads 0% with grounding on and 88.9% with it off |
| Tool descriptions | Cutting descriptions to one line leaves selection accuracy unchanged but raises forbidden-tool calls from 0% to 4.5% |

The models behind these numbers are deterministic stubs, not providers. The
point is that the measurement harness works and the comparisons are
reproducible; run the same commands with `--model anthropic:claude-opus-5` for
numbers about a model.

---

## Testing

```bash
uv run pytest              # default run
uv run pytest -m live      # calls real APIs, needs keys
uv run ruff check src/ tests/
```

A few tests are worth calling out because of what they protect:

| Test | Guards against |
|---|---|
| `test_no_vendor_leak.py` | An SDK import escaping `adapters/` (AST-based, with an inverse check) |
| `test_prefix_stable.py` | A variable field leaking into the cache prefix and silently multiplying the bill |
| `test_schema_regression.py` | A schema changing without anyone noticing that old eval results are now incomparable |
| `test_eval_harness.py` | The eval harness silently returning "correct" for everything |
| `test_executor_gates.py` | A traceback reaching the model, or a refusal disclosing a tool it may not use |

## License

MIT.
