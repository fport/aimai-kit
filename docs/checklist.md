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

--8<-- "provider.md"

## Writing a prompt

→ [2. Prompts and context](02-prompts.md)

--8<-- "prompt.md"

## Asking for structured output

→ [2. Prompts and context](02-prompts.md#schema-design-is-an-output-quality-decision)

--8<-- "structured.md"

## Adding a tool

→ [3. The tool layer](03-tools.md)

--8<-- "tools.md"

## Running an agent loop

→ [4. The agent loop](04-agent.md)

!!! warning "This loop is a study, not a runtime"

    Use [Strands Agents](https://strandsagents.com/) in production. The list below
    still applies — it is what any framework has to get right on your behalf.

--8<-- "agent.md"

## When the run gets long

→ [5. The harness](05-harness.md)

--8<-- "harness.md"

## Before you ship

Cross-cutting, and the part that is easiest to leave for later.

--8<-- "ship.md"

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

---

!!! done "One source, two places"

    Each block above also appears at the end of the chapter it comes from, included
    from the same file under `snippets/`. Edit it there and both places move together —
    a checklist that drifts from the chapter explaining it is worse than no checklist.
