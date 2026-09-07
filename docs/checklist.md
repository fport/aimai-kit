# Production checklist

Every item below is something one of the five chapters had to fix. None of it is
generic advice — each line names a failure that has a section explaining it, and most
of them are quiet failures: the kind that ship, work in staging, and turn up later on
an invoice or in an incident.

Use it by task. You are about to write a prompt, or add a tool, or set a budget: read
that block.

!!! done "Unchecked is fine. Unconsidered is not."

    Plenty of these do not apply to a small internal tool. The point is to have
    decided — an item you skipped on purpose is a decision, an item you never saw is a
    bug waiting for traffic.

    A copy-paste version for a PR template is [at the bottom](#copy-paste).

---

## Wiring a provider

→ [1. The provider layer](01-provider.md)

- [ ] **The SDK's own retry is off** (`max_retries=0`). Two retry layers multiply:
      three of yours times three of theirs is nine calls and nine times the bill.
- [ ] **Retryability is a property of the error class**, not a string search in the
      message. Provider wording changes without notice; your retry logic should not.
- [ ] **`Retry-After` beats your backoff.** The provider knows when it will be ready
      and you do not.
- [ ] **The backoff has jitter.** Fifty clients that all get a 429 and all wait exactly
      two seconds recreate the spike that caused it.
- [ ] **There is a total deadline**, not just an attempt count. Three attempts each
      honouring a 60-second `Retry-After` is a three-minute request nobody budgeted for.
- [ ] **No retry once the stream started.** The user already saw the first chunk;
      retrying restarts the answer in front of them.
- [ ] **Cached tokens are normalised.** Anthropic reports `cache_read_input_tokens`
      *outside* `input_tokens`, OpenAI reports them *inside*. Get this wrong and your
      cost dashboard disagrees with the invoice, in a direction you only notice at the
      end of the month.
- [ ] **A fallback is an event.** `llm_fallbacks_total` goes up. A fallback that
      rescues you silently means the primary provider can be down for a week.
- [ ] **TTFT and total duration are separate metrics.** For a streaming UI they answer
      different questions, and one average hides both.
- [ ] **You look at p95, not the mean.** The mean is the experience of nobody.

## Writing a prompt

→ [2. Prompts and context](02-prompts.md)

- [ ] **The prompt is a versioned file**, not a string in Python. In a diff a string
      change is "one line changed" and there is no way back to which text produced
      which result.
- [ ] **Every run records its `prompt_ref`** (`name@vN+fingerprint`). The version is
      for humans, the fingerprint is for the case where somebody edited v2 without
      bumping it.
- [ ] **`StrictUndefined` is on.** A missing template variable must raise. Jinja's
      default renders it as empty, and you file the result under "the model
      hallucinated" when in fact the context was blank.
- [ ] **The cache prefix is stable.** Nothing that changes per call — a timestamp, a
      request id, the user's name — appears before the cache breakpoint. This is the
      bug you find on the invoice, not in the tests.
- [ ] **The prefix signature is pinned in a test**, so the next person to add a line to
      the system prompt finds out immediately.
- [ ] **Trimming is a decision with a report line.** `documents[:10]` is a guess that
      leaves no trace; if the eleventh document was the one that mattered there is no
      way to find out.
- [ ] **Non-trimmable sections raise instead of being cut.** A system running on half
      its instructions cannot explain why it answered wrongly.
- [ ] **There is a safety margin under the window.** Local token counts are estimates
      and drift 10–20% on Anthropic and Gemini; filling to the limit means a 400
      whenever the estimate comes in low.
- [ ] **Untrusted content sits in a delimited block**, never in the system prompt, and
      the instructions say the block is data.
- [ ] **The trust boundary has a test** with an actual injection string in it.

## Asking for structured output

→ [2. Prompts and context](02-prompts.md#schema-design-is-an-output-quality-decision)

- [ ] **The schema is strict**: `additionalProperties: false`, every field `required`,
      optionals expressed as `anyOf: [type, null]`.
- [ ] **Known value sets are `Literal`, not free text.** This is an accuracy change,
      not a validation change — free text invents its own vocabulary.
- [ ] **Money is integer minor units.** As a float, "1,250,000.50" arrives in more
      shapes than you want to parse.
- [ ] **Field descriptions are written as instructions to the model**, not as
      documentation for a reader. They are the part the model actually obeys.
- [ ] **The repair loop is bounded** at two or three attempts. Unbounded, a bad prompt
      becomes a bill.
- [ ] **Repair errors are readable.** A raw `ValidationError` repr is not a message a
      model can act on.
- [ ] **The mean attempt count is alarmed on.** Near 1.0 the schema fits; drifting
      toward the ceiling means the prompt or the schema is wrong, and the loop is
      hiding it.
- [ ] **Citations are verified against the source.** A schema validates shape, never
      content — a well-formed citation to a document that does not say that is exactly
      what a model produces under pressure.

## Adding a tool

→ [3. The tool layer](03-tools.md)

- [ ] **The schema comes from the signature.** One source of truth; a hand-written
      schema drifts from the function on the first refactor.
- [ ] **Side effects are declared on the spec** — idempotent, destructive, needs
      approval — not implied by the description.
- [ ] **The allowlist filters the declaration.** A tool the caller may not use is never
      shown to the model, so it cannot be called and then refused.
- [ ] **`not_allowed` does not name the tool.** An error that confirms a tool exists is
      an enumeration oracle.
- [ ] **Server context is injected from the call.** `user_id` and `tenant_id` come from
      your session, never from a model-supplied argument. This is the whole ballgame.
- [ ] **Every rejection has a distinct code** and a message the model can act on —
      which field, what was expected.
- [ ] **Timeouts run on a worker thread.** A hanging tool must not hang the loop.
- [ ] **Truncation is announced in the result.** A tool returning 200 KB should say it
      was cut, not quietly return a prefix.
- [ ] **Writes are sequential, reads are parallel.** Concurrency is a property of the
      tool, not of the executor.
- [ ] **Idempotency keys are derived from the call signature**, not requested from the
      model. Asking the model for a key means trusting it to notice it is retrying.
- [ ] **The boundary sentences stay in the description.** Measured on the tool golden
      set: cutting a description to its first sentence left selection accuracy at 90.9%
      and moved the forbidden-call rate from 0.0% to 4.5%. Descriptions are a safety
      control, and the accuracy metric does not show it.

## Running an agent loop

→ [4. The agent loop](04-agent.md)

- [ ] **All four budgets are set**: steps, tokens, cost, seconds. Each bounds a
      different failure and none of them substitutes for another.
- [ ] **Budgets are checked before a step.** Finding out afterwards is an audit.
- [ ] **A missing pricing catalog does not silently disable the cost budget.** Spend
      stays at zero and the budget never fires — make that visible in metrics rather
      than discovering it in billing.
- [ ] **Every tool call gets a result**, including the ones that failed. A tool call
      with no result is a malformed conversation that most providers reject.
- [ ] **There is a final tool-free turn** when the budget runs out, so the user gets an
      answer instead of a truncated loop.
- [ ] **Loop detection warns before it stops**, and the warning is in the thread where
      the model can read it.
- [ ] **`stop_reason` is recorded and distinguishable.** "Finished" and "ran out of
      steps" must not look the same downstream.
- [ ] **The thread serialises**, so resuming is passing it back rather than a recovery
      subsystem.
- [ ] **Metrics are read in order: loop rate → budget stop rate → recovery rate.** A
      loop inflates everything below it; tuning budgets while the loop rate is high
      just raises the ceiling on wasted work.
- [ ] **A low recovery rate is read as a tool-layer problem**, not a budget one — it
      means the error messages are not actionable.

## When the run gets long

→ [5. The harness](05-harness.md)

- [ ] **Context is assembled from segments and trimmed from the end.** Trimming from
      the front removes the instructions.
- [ ] **Large payloads are spilled, not inlined.** Keep the reference and the summary;
      the 200 KB does not need to be in every subsequent turn.
- [ ] **Compaction is threshold-triggered, not per step.** Compacting every step spends
      a model call to save tokens you were not short of.
- [ ] **Compaction happens at a step boundary**, never in the middle of a tool turn.
- [ ] **The compaction prompt is a versioned file**, and the version is recorded with
      the state it produced. Compaction is lossy; "which summariser wrote this" is a
      question you will be asked.
- [ ] **The compaction prompt has a needle test.** A summariser that preserves one
      number is not a summariser that preserves numbers — write the test with dates,
      ids and amounts in it.
- [ ] **Memory writes go through a deterministic gate**, and refusals are counted.
      A memory that accepts everything is a slower way to lose the thread.
- [ ] **Stale memory is filtered on recall**, not on write. What was true when written
      is not what is true now.
- [ ] **A sub-agent returns a constrained result with verifiable evidence**, not prose.
      Prose gives the caller something to interpret instead of something to use.
- [ ] **You know which of your isolation layers is the real boundary.** Two of the
      three usually are not.

## Before you ship

Cross-cutting, and the part that is easiest to leave for later.

- [ ] **Every number you publish is reproducible by a command in the repo.** If you
      cannot re-run it, it is a claim, not a measurement.
- [ ] **The counters are wired to something that alarms**, not just exported:
      `llm_call_errors_total`, `llm_retries_total`, `llm_fallbacks_total`,
      `tool_calls_total`, `agent_budget_stops_total`, `context_segments_dropped_total`,
      `memory_writes_refused_total`.
- [ ] **The fallback path has actually been exercised.** Break the primary provider in
      staging. An untested fallback is a second outage waiting inside the first.
- [ ] **A run is identifiable end to end**: `prompt_ref`, model, thread id, stop reason,
      in the same log line.
- [ ] **Budgets are configurable without a deploy.** They are your kill switch; a kill
      switch behind a release train is not one.
- [ ] **Cost per run is measured on real traffic shape**, not on the happy path. The
      runs that loop are the ones that cost money.
- [ ] **Keys are absent from the repo and from error messages.** A failing request
      prints the request.

---

## Copy-paste

Drop this into a PR template or an issue and delete what does not apply.

```markdown
### Provider
- [ ] SDK retry disabled, one retry layer
- [ ] retryability on the error class, not the message text
- [ ] Retry-After honoured; jitter; total deadline
- [ ] no retry after the first streamed chunk
- [ ] cached tokens normalised across providers
- [ ] fallbacks counted, TTFT separate from duration, p95 not mean

### Prompt
- [ ] versioned file; prompt_ref recorded on every run
- [ ] StrictUndefined on
- [ ] cache prefix stable, signature pinned in a test
- [ ] trimming reports; non-trimmable sections raise; safety margin under the window
- [ ] untrusted content delimited and labelled as data; injection test exists

### Structured output
- [ ] strict schema (additionalProperties false, all required, anyOf null)
- [ ] Literal over free text; money in integer minor units
- [ ] descriptions written as instructions
- [ ] repair loop bounded, errors readable, mean attempts alarmed
- [ ] citations verified against the source

### Tools
- [ ] schema derived from the signature
- [ ] side effects on the spec; allowlist filters the declaration
- [ ] not_allowed does not name the tool
- [ ] server context injected, never model-supplied
- [ ] distinct error codes; timeouts off the loop; truncation announced
- [ ] writes sequential, reads parallel; idempotency key from the call signature
- [ ] tool descriptions keep their boundary sentences

### Agent loop
- [ ] four budgets set and checked before the step
- [ ] every tool call gets a result; final tool-free turn on budget exhaustion
- [ ] loop detection warns then stops; stop_reason recorded
- [ ] thread serialises
- [ ] metrics read loop rate -> budget stop rate -> recovery rate

### Harness
- [ ] segments trimmed from the end; large payloads spilled
- [ ] compaction threshold-triggered, at a step boundary, prompt versioned
- [ ] needle test on the compaction prompt
- [ ] memory write gate deterministic, refusals counted, stale filtered on recall
- [ ] sub-agents return constrained results with evidence

### Ship
- [ ] published numbers reproducible from the repo
- [ ] counters alarmed, not just exported
- [ ] fallback path exercised in staging
- [ ] prompt_ref + model + thread id + stop reason in one log line
- [ ] budgets configurable without a deploy
- [ ] keys absent from the repo and from error messages
```
