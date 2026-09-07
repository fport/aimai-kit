# aimai-kit

A framework-free LLM engineering toolkit in one Python package.

| Layer | Package | What it adds |
|---|---|---|
| 1 | `provider/` | Token/cost/latency measurement, four adapters, retry and fallback |

Later layers (prompts, tools, agent loop, harness) build on the `LLMClient`
protocol defined here.

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

```bash
# Compare models: TTFT from streaming, real usage from one complete call
uv run model-probe --prompt evals/probe/sample-prompt.txt \
  --models anthropic:claude-opus-5 anthropic:claude-haiku-4-5 -n 5
```

## Why it looks like this

One internal message format and five error classes. Retry decisions are driven
by the error *class*, never by matching message text. Cached tokens are
normalized to a single rule across providers, because Anthropic reports them
outside `input_tokens` and every cost calculation downstream depends on which
convention you picked.

Full reasoning, including what was rejected and why: **[docs/01-provider.md](docs/01-provider.md)**.

## Testing

```bash
uv run pytest              # default run
uv run pytest -m live      # calls real APIs, needs keys
uv run ruff check src/ tests/
```

`test_no_vendor_leak.py` is worth calling out: it walks the AST of every
source file and fails if a vendor SDK is imported outside
`provider/adapters/`. It also runs the inverse check, so deleting the SDK
calls by accident cannot leave the suite green.

## License

MIT.
