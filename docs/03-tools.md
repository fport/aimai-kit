# Tool layer — why it looks like this

Three responsibilities, three files, and keeping them apart is the main
design decision:

| Question | Where it is answered |
|---|---|
| What tools exist, and who may see them? | `decorator.py`, `registry.py` |
| How does each provider want to be told? | `export.py` |
| What actually happens when one runs? | `executor.py` |

Collapsing these into one class is the usual shortcut, and it is why tool
authorization so often ends up inside the agent loop — where it cannot be
tested without starting a run.

## The schema comes from the signature

Writing the function and its JSON Schema separately guarantees they drift.
Someone renames a parameter, the schema still advertises the old name, and the
model keeps sending arguments that no longer bind. Nothing errors; the tool
just receives defaults.

`@tool` derives the schema from `inspect.signature`, so that class of bug is
structurally impossible.

Supported types are restricted to `str`, `int`, `float`, `bool`, `date`,
`Literal` and lists of those. An unsupported annotation raises at import time
instead of producing a schema the provider rejects at runtime. This is a
design choice, not a limitation of the technique: a tool that needs a deeply
nested argument object is almost always two tools.

An empty docstring is an error. The description is the only thing the model
has for deciding *when* to call a tool, and leaving it blank guarantees wrong
selection.

One implementation detail worth knowing: with `from __future__ import
annotations` in effect, every annotation arrives as a string, so the decorator
uses `get_type_hints(include_extras=True)` rather than `param.annotation`. A
type defined inside an enclosing function cannot be resolved that way, so the
decorator raises with an explicit message instead of letting a bare
`NameError` surface from inside `typing`.

## Side effects live on the spec, not in the schema

`side_effect` and `requires_approval` are properties of the tool, not
arguments to it. Putting them in the schema would let the model set
`requires_approval=false` on its own call, which is not an approval gate.

The operator sets them in the registry; the executor reads them from there.

## The allowlist filters the declaration

`registry.visible(allowlist)` filters what is *advertised*, not just what is
permitted to run.

If a tool the caller may not use is still declared to the model, the model
will eventually call it, the executor will refuse, and a step is burned on a
refusal that was avoidable. Worse, the refusal message teaches the model that
the tool exists.

This is also the answer to "what happens with twenty tools": you do not send
twenty. You send the subset this request is allowed to use.

`visible()` sorts by name. Not cosmetic — tool declarations sit inside the
cached prompt prefix, and set ordering would produce different bytes on every
process restart.

## Three exports, one schema

The providers disagree about two things and nothing else:

| Provider | Shape | Schema key |
|---|---|---|
| OpenAI Responses | flat | `parameters` |
| OpenAI Chat | nested under `function` | `parameters` |
| Anthropic | flat | `input_schema` |

That is exactly the kind of difference which, left unabstracted, gets copied
into every call site. One internal representation, three thin exporters, and
`export_for(provider, tools)` is the only place above the adapter layer that
consults provider identity — and it consults a name, not a type.

## Five gates

Each gate answers a different question and produces a message the model can
act on, never a stack trace:

| Gate | Code | Retryable | The message |
|---|---|---|---|
| Does the tool exist? | `no_such_tool` | yes | lists what does exist |
| Is the caller allowed? | `not_allowed` | no | does **not** name the tool |
| Parseable JSON? | `bad_json` | yes | says where parsing failed |
| Matches the schema? | `bad_args` | yes | names the offending field |
| Needs approval? | `needs_approval` | no | stops the loop cleanly |

The asymmetry between gates 1 and 2 is deliberate. Gate 1 lists the available
tools, because a model that called `get_customer` when the tool is
`fetch_customer` corrects itself on the next turn. Gate 2 does not, because
telling an unauthorized caller which tools exist is a disclosure — and a model
that learns a tool exists will keep trying it.

`retryable` is not the same as `ok`. A schema error is retryable: the model
can fix its own arguments. A permission error is not: retrying changes
nothing, and the loop should stop rather than burn steps.

## After the gates

**Server context is injected from the call.** `user_id` and `tenant_id` come
from the session and are stripped from the schema. Tenancy as a model-supplied
field means the model can claim to be another tenant, and no amount of
prompting fixes that. A test asserts the parameters are absent from the
schema.

**Timeouts use a worker thread.** A hanging tool does not hang the agent; it
produces a `timeout` result the loop can reason about. The thread is left
running, because Python cannot kill one — a tool that needs hard cancellation
belongs in a subprocess.

There are two thread pools, not one. `call_many` submits into a fan-out pool
and each of those calls submits again to enforce its timeout. Sharing one pool
means the outer tasks occupy every worker and the inner ones queue behind
them, so timeouts fire on work that never started. That bug was found by a
test asserting result order.

**Truncation is announced.** A tool returning 200 KB of JSON does not fail —
it quietly eats the window and the next few turns degrade for no visible
reason. The result is cut to `max_result_chars` and the cut is stated in the
content, because an answer built on half a document with no indication
anything was missing is worse than a short answer.

**`raw` never enters the context.** It goes to the trace, so debugging can see
the full payload while the model only ever sees `content`.

## Parallel reads, sequential writes

Read-only calls are independent by definition, so running them one after
another wastes wall-clock time for no safety gain.

Side-effecting calls run **sequentially in the order the model declared
them**, because they may depend on each other ("cancel the order, then notify
the customer") and because a partial failure is far easier to reason about in
a known order.

A failure in one call never loses the others: every call gets its own result.

## Idempotency without asking the model

The call signature is the tool name plus normalized arguments, so
`{"a":1,"b":2}` and `{"b":2,"a":1}` are recognized as the same call.

The key is never requested from the model. Asking for an idempotency key means
the guarantee holds exactly as often as the model remembers to send a stable
one, which is not a guarantee.

Side-effecting results are stored by signature, so a resumed run does not
charge a card twice. The limit is stated plainly: the process can die after
the tool ran and before the result was written. This narrows the window; only
an idempotent tool closes it.

Read-only calls are deliberately **not** cached — caching a read would hide
data that changed between calls.

## What descriptions are worth, measured

Every example tool's description carries three things, and the third is the
one people leave out:

1. what the tool does,
2. when **not** to use it, pointing at the neighbouring tool,
3. whether it has a side effect.

The experiment (`scripts/tool_description_experiment.py`) runs the same golden
cases against three variants of the same registry — identical schemas, only
the description text differs:

| Variant | Selection accuracy | Forbidden-call rate |
|---|---|---|
| full | 90.9% | 0.0% |
| boundary sentences removed | 90.9% | 0.0% |
| first sentence only | 90.9% | **4.5%** |

The finding is not the one that was expected, which is why it is worth
reporting: with this selector, description quality did not move selection
accuracy at all. It moved the **safety** number. Cutting descriptions to one
line left the agent just as likely to pick the right tool and measurably more
likely to reach for the destructive one.

That says something about which metric belongs on a dashboard. Selection
accuracy is a quality signal; forbidden-call rate is a security signal, and it
degraded first.

The selector is a stub, so the absolute numbers are not a claim about any
provider. What transfers is that the experiment costs nothing and can run on
every description change.
