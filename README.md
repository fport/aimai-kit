<p align="center">
  <img src="https://raw.githubusercontent.com/fport/aimai-kit/main/assets/header.png" alt="aimai-kit" width="860">
</p>

<p align="center">
  <a href="https://github.com/fport/aimai-kit/actions/workflows/ci.yml"><img src="https://github.com/fport/aimai-kit/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/aimai-kit/"><img src="https://img.shields.io/pypi/v/aimai-kit?color=8FE64A&label=pypi" alt="PyPI"></a>
  <a href="https://pypi.org/project/aimai-kit/"><img src="https://img.shields.io/pypi/pyversions/aimai-kit?color=8FE64A" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-8FE64A" alt="License: MIT"></a>
</p>

A framework-free LLM engineering toolkit in one Python package: provider
adapters, prompt and context engineering, structured outputs, a tool layer,
a bounded agent loop, and a harness for long-running work.

Five layers, each built on the one below it, each with its own measurements.

**Documentation: [fport.github.io/aimai-kit](https://fport.github.io/aimai-kit/)**
— the reasoning behind every layer, with examples. Available in
[English](https://fport.github.io/aimai-kit/) and
[Türkçe](https://fport.github.io/aimai-kit/tr/).

| Layer | Package | What it adds |
|---|---|---|
| 1 | `provider/` | Token/cost/latency measurement, four adapters, retry and fallback |
| 2 | `prompts/` | Versioned prompts, context budget, structured output, a repair loop |
| 3 | `tools/` | Schemas from signatures, three provider exports, a five-gate executor |
| 4 | `agent/` | A bounded loop, four budgets, loop detection, checkpoints |
| 5 | `harness/` | Segments, spill, compaction, a memory store, sub-agents |

**343 tests**, no vendor SDK outside `provider/adapters/`, and every layer
runnable without an API key.

---

## Install

```bash
pip install "aimai-kit[providers]"
```

From source:

```bash
uv sync --all-extras --group dev
cp .env.example .env     # add your keys
uv run pytest            # 343 tests, live ones excluded
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

An agent with tools:

```python
from aimai_kit.agent import Agent, Budgets, Thread
from aimai_kit.tools import CallContext, ToolExecutor
from aimai_kit.tools.examples.orders import build_registry, seed_database

seed_database()
executor = ToolExecutor(build_registry())
agent = Agent(client, executor, budgets=Budgets(max_steps=8, max_seconds=60))
run = agent.run(Thread(), "What is the status of order 1002?",
                ctx=CallContext(user_id="u-1", tenant_id="t-1"))
print(run.stop_reason, run.answer)
```

## Command line

```bash
# Compare models: TTFT from streaming, real usage from one complete call
uv run model-probe --prompt evals/probe/sample-prompt.txt \
  --models anthropic:claude-opus-5 anthropic:claude-haiku-4-5 -n 5

# Extraction quality against a golden set (no API key needed)
uv run prompt-lab eval --prompt extract_contract@v2 --schema v2 \
  --pricing config/pricing.toml --pricing-model claude-opus-5

# With a real model
uv run prompt-lab --model anthropic:claude-opus-5 eval
```

---

## Why each layer looks the way it does

Short version below; the full reasoning, including what was rejected and why,
is in `docs/`.

**[Provider](https://fport.github.io/aimai-kit/01-provider/)** — one internal message format and five
error classes. Retry decisions are driven by the error *class*, never by
matching message text. Cached tokens are normalized to a single rule across
providers, because Anthropic reports them outside `input_tokens` and every
cost calculation downstream depends on which convention you picked.

**[Prompts and context](https://fport.github.io/aimai-kit/02-prompts/)** — prompts are versioned files
identified as `name@vN+fingerprint`. The document goes into a user message,
never the system block, so the cache prefix stays byte-identical across
requests. Trimming is an explicit decision that produces a report line, and
the non-trimmable sections raise rather than shrink.

**[Tools](https://fport.github.io/aimai-kit/03-tools/)** — the schema is derived from the function
signature, so the two cannot drift apart. Five gates run before anything
executes, each producing a message the model can act on. Server context
(`tenant_id`) is injected from the call and is absent from the schema, so a
model cannot claim to be another tenant.

**[Agent loop](https://fport.github.io/aimai-kit/04-agent/)** — four budgets, one stop reason, and a
final tool-free turn so a stopped run still answers. Every tool call gets a
result, including refused ones. Repetition is warned about before it is
stopped, because a warned model usually recovers.

**[Harness](https://fport.github.io/aimai-kit/05-harness/)** — the atomic unit of context is a segment,
not a message, so trimming can never separate a tool call from its result.
Large output spills to disk with a reference the agent can follow. Compaction
converts old turns instead of dropping them, with a versioned prompt that
names what must survive.

---

## Measurements

Every number below is reproducible from this repository with no credentials.
Full tables and the honest caveats are in
**[Measurements](https://fport.github.io/aimai-kit/measurements/)**.

| Experiment | Finding |
|---|---|
| Schema v1 vs v2 | Grounding 0% → 100%, at 0.06 more attempts and 16% more cost per document |
| Grounding attribution | v1's `start_date` reads 0% with grounding on and 88.9% with it off — the drop is the missing citation field, not extraction |
| Tool descriptions | Cutting descriptions to one line leaves selection accuracy unchanged but raises forbidden-tool calls from 0% to 4.5% |
| Loop detection | p95 steps 7 → 3, at the cost of completion 100% → 75% on runs that would have recovered on their own |
| Harness configurations | Naive trim 101k tokens and no answer; compaction 69.5k and no answer; compaction plus a sub-agent 12k and the answer survives |

The models behind these numbers are deterministic stubs, not providers. That
is deliberate: the point is that the measurement harness works and the
comparisons are reproducible. Run the same commands with `--model
anthropic:claude-opus-5` for numbers about a model.

---

## Testing

CI runs the suite on Python 3.12 and 3.13, and a second job re-runs every
measurement script and fails if a committed result changed. A table in the
docs that no longer matches the code is a broken build, not a reader's
problem.

```bash
uv run pytest                 # 343 tests
uv run pytest -m live         # calls real APIs, needs keys
uv run ruff check src/ tests/
```

A few tests are worth calling out because of what they protect:

| Test | Guards against |
|---|---|
| `test_no_vendor_leak.py` | An SDK import escaping `adapters/` (AST-based, with an inverse check) |
| `test_prefix_stable.py` | A variable field leaking into the cache prefix and silently multiplying the bill |
| `test_schema_regression.py` | A schema changing without anyone noticing that old eval results are now incomparable |
| `test_segments.py` | A trim separating a tool call from its result |
| `test_compaction.py` | Compaction dropping a planted fact — three needles, both prompt versions |
| `test_eval_harness.py` | The eval harness silently returning "correct" for everything |

---

## Known limits

- **The golden sets are synthetic.** `scripts/generate_golden_set.py` writes 36
  contracts, 10 of them deliberate edge cases. Replace them with your own
  documents for a real evaluation; the `EDGE_CASES` map is the guide for what
  to look for.
- **The stubs are not models.** They perform real extraction and real
  selection, but they know the shape of the synthetic data, so their accuracy
  is optimistic.
- **The pricing catalog only ships Anthropic rows.** OpenAI and Gemini are
  commented out in `config/pricing.toml`; fill them from your own billing
  page. A missing model produces a visible "window not in catalog" warning
  rather than a silent zero.
- **Synchronous only.** Async adds no teaching value at this size.
- **Isolation is three layers and only two are in this repository.** The
  in-process path jail and the cleaned subprocess environment are here;
  closing the network belongs to deployment, and it is the layer that matters
  most.

## Documentation site

```bash
uv sync --group docs
uv run mkdocs serve        # http://127.0.0.1:8000
```

Built with MkDocs Material, two locales (`en`, `tr`), deployed to GitHub Pages
on every push that touches `docs/`. The build runs with `--strict`, so a broken
internal link fails CI rather than becoming a 404 someone finds later.

## Brand assets

`assets/` holds the mark in both forms. `_generate.py` builds all of them, so
a logo nobody can regenerate is not what ships here:

```bash
python assets/_generate.py            # the SVGs
uvx --from pillow python assets/_generate.py --png   # the rasters
```

| File | Use |
|---|---|
| `header.svg` / `header.png` | README and docs banner |
| `logo.svg` | Wordmark for slides and docs |
| `icon.svg` / `icon.png` | Avatar, favicon, social card |

## License

MIT.
