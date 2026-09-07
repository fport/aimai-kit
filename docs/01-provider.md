# 1. Provider layer

The job of this layer is to make every provider look the same to everything
above it, without flattening away the differences that matter. Those are two
opposing pressures, and most of the decisions here are about where to put the
line between them.

!!! done "What we built here"

    The `ChatRequest` / `ChatResult` / `Usage` / `Message` internal model, the
    `LLMClient` protocol, five error classes, four adapters (OpenAI,
    Anthropic, Gemini, Azure), a retry-and-fallback wrapper, and the
    `model-probe` measurement CLI. All four later layers sit on this protocol
    and none of them required touching an adapter.

## The internal message format

`ChatRequest` / `ChatResult` / `Usage` / `Message` are the only vocabulary the
rest of the package speaks. Three choices in them are worth explaining.

**`system` is a top-level field, not an entry in the message list.** Anthropic
and Gemini already expect it that way. OpenAI wants it as a message, and
converting one into the other is a single line in the adapter. Normalizing in
the other direction — burying the system prompt inside the message list and
digging it out again in two of three adapters — would mean string surgery on
every call, in the place least suited to it.

```python
from aimai_kit.provider.types import ChatRequest, Message, Role

req = ChatRequest(
    messages=[Message(role=Role.USER, content="What is the fee?")],
    system="You are a legal assistant.",   # top level
    max_output_tokens=512,
)
```

Each adapter translates it into its own shape:

```python
# anthropic_.py
kwargs["system"] = req.system                 # top-level parameter
# openai_.py
kwargs["instructions"] = req.system            # its own parameter
# gemini_.py
config["system_instruction"] = req.system      # inside the config
```

**Unused fields exist and stay empty.** `ChatRequest` carried `json_schema`
and `tools` from the beginning, filled by later layers. Adding a field is
backward compatible; renaming one is not. The whole point of a stable
protocol is that the layer above can grow without the layer below changing,
and the way to get that is to leave room rather than to guess correctly.

**Provider-specific settings go in `extra`.** Gemini's `thinking_config` and
OpenAI's `reasoning_effort` have no equivalent in the other providers. Putting
them in the internal model would pollute it; leaving them unreachable would
force callers around the abstraction. A namespaced escape hatch keeps both
properties.

```python
req = ChatRequest(
    messages=[...],
    extra={"gemini": {"thinking_config": {"thinking_budget": 2048}}},
)
```

## The trap that costs money: usage field names

This is the single most expensive detail in the layer.

OpenAI reports cached tokens *inside* `input_tokens`, with a detail object
breaking out the cached portion. Anthropic reports `cache_read_input_tokens`
*separately*, not included in `input_tokens`. Both are reasonable; they are
not the same.

Pick one convention and normalize to it in the adapters. This package treats
cached tokens as a **subset of input tokens** — OpenAI's convention — and the
Anthropic adapter folds cache reads and cache writes into `input_tokens` on
the way in.

Skip that normalization and Anthropic costs come out systematically low. Not
by a rounding error: on a cache-heavy workload the cached portion is most of
the input. The failure is silent, appears only in a billing report, and
looks like a pricing bug rather than an accounting one.

Here is the normalization, in the Anthropic adapter:

```python
cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0

Usage(
    input_tokens=usage.input_tokens + cache_read + cache_write,
    output_tokens=usage.output_tokens,
    cached_input_tokens=cache_read,
)
```

`ModelPricing.cost()` now raises when `cached_input_tokens > input_tokens`,
which is the shape an unnormalized adapter produces:

```pycon
>>> price.cost(input_tokens=100, output_tokens=10, cached_input_tokens=200)
ValueError: cached_input_tokens must be a subset of input_tokens (200 > 100).
Some adapter is not normalizing its usage fields.
```

## Error classification

Five classes, and the classification carries the retry decision:

| Class | Retry? | Because |
|---|---|---|
| `RateLimited` | yes | the provider said to wait, and told you how long |
| `TransientError` | yes | 5xx and connection failures are worth one more try |
| `InvalidRequest` | no | the same 400 comes back |
| `AuthError` | no | the key is still wrong |
| `AllProvidersFailed` | no | every link in the chain is down |

`retryable` lives on the class, so the retry policy reads it from one place:

```python
class RateLimited(LLMError):
    retryable = True

class InvalidRequest(LLMError):
    retryable = False
```

The alternative — inspecting error messages for words like "rate limit" —
breaks silently the day a provider rewrites its copy, and the breakage looks
like an outage.

## Retry and fallback

**The SDK's own retry is disabled** (`max_retries=0`). Two layers of retry
multiply: three attempts over two layers is six calls, and a deadline
computed for three is meaningless. Exactly one layer decides.

**There is a total deadline.** Three attempts times a 60-second `Retry-After`
is a request that hangs for three minutes. The user's client gave up long
before. Without a deadline, retrying becomes an outage of its own.

**Jitter is not decoration.** Fifty clients that all receive a 429 and all
wait exactly two seconds come back at the same instant and hit the same wall.
Random spread is what turns a thundering herd back into a queue.

**No retry on streaming.** Once the first chunk reached the user, retrying
means erasing half a sentence on screen. That is a UI decision and belongs to
the caller; the library does not hide it.

```python
policy = RetryPolicy(
    max_attempts=3,
    base_delay_s=0.5,
    max_delay_s=20.0,
    jitter_s=0.25,
    total_deadline_s=45.0,   # retrying must not become an outage itself
    honor_retry_after=True,  # the provider's estimate beats ours
)
```

**Falling back is an event, not a quiet rescue.** `llm_fallbacks_total` is
exported with labels.

```python
resilient = ResilientClient(
    primary,
    [backup],
    policy=policy,
    on_fallback=lambda src, dst, err: alert(f"{src} -> {dst}: {err}"),
)
``` A service that silently degrades looks healthy on every
dashboard even while the primary provider is completely down — users are
still getting answers, just slower, more expensive, and from a weaker model.
The fallback rate needs an alert on it precisely because the error rate will
not show anything.

## Measuring: why TTFT and duration are separate

TTFT is what a user feels. Total duration is what a capacity plan needs. A
run with 200 ms TTFT and 9 s duration and one with 4 s TTFT and 5 s duration
have similar averages and completely different user experiences.

`model-probe` measures them in the only way that actually works: N streaming
runs give TTFT and duration, then one `complete` call gives the real `usage`,
which streaming may not report.

```bash
uv run model-probe --prompt evals/probe/sample-prompt.txt \
  --models anthropic:claude-opus-5 anthropic:claude-haiku-4-5 -n 5
``` The cost is N+1 calls. The payoff is the
drift column — the local tiktoken estimate next to the provider's reported
count. tiktoken is the OpenAI vocabulary, and on Anthropic and Gemini that
drift reaches 10-20%, which is why the context budget carries a safety margin
rather than filling to the limit.

## Percentiles, not means

Latency in an LLM service is skewed, so the reports return p50/p95/p99.

One caveat is built into the tests: nearest-rank at small N swallows outliers.

```pycon
>>> values = [100.0] * 19 + [10_000.0]
>>> percentiles(values)
{50: 100.0, 95: 100.0, 99: 10000.0}
```

With twenty runs, p95 is the nineteenth value — a single ten-second run does
not appear until p99. "p95 is fine" does not mean "there are no bad runs".
Write N next to the SLO.

Failed calls are excluded from latency (a 429 returning in 40 ms means no work
happened) but included in cost (the input tokens may still have been billed).

## The boundary that is tested

Vendor SDKs are imported only under `provider/adapters/`, and
`test_no_vendor_leak.py` enforces it with an AST walk rather than a regex, so
comments and string literals do not raise false alarms. It also runs the
inverse check — that the adapters really do import an SDK — because otherwise
deleting the SDK calls by accident would leave the suite green and the
guarantee empty.

```python
@pytest.mark.parametrize("path", _source_files(), ids=lambda p: p.name)
def test_vendor_sdk_does_not_leak_outside_adapters(path: Path) -> None:
    roots = _import_roots(ast.parse(path.read_text(encoding="utf-8")))
    assert not roots & FORBIDDEN_ROOTS
```

---

## Checklist

Before this layer goes to production:

--8<-- "provider.md"


The rest — tools, budgets, the release itself — and a copy-paste version for a PR
template: **[production checklist](checklist.md)**.
