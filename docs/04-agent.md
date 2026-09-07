# Agent loop — why it looks like this

The loop is short, and that is the design. Everything it could have absorbed
lives behind its own seam:

| Concern | Where |
|---|---|
| Tool execution | the tool layer's executor |
| Request construction | the prompt layer |
| Telemetry | the provider layer's resilient client |
| Loop detection | its own object, with its own tests |

What is left is the part that is genuinely about looping: check the budget,
call the model, hand any tool calls to the executor, feed every result back,
repeat.

## Stateless agent, stateful thread

The `Agent` holds configuration. The `Thread` holds everything else:
messages, step count, spend, trace, tool-result cache, loop counters.

Two things follow for free. A stateless agent can be shared across concurrent
requests. And checkpointing is not a subsystem — it is `to_dict` and
`from_dict` on one object. Had state been spread across the agent, the
executor and a few module-level caches, checkpointing would have needed a
design.

The trace is part of the state rather than a logging side channel, for the
same reason: a run you can resume but not explain is only half recovered.

## Four budgets

Each bounds a different failure:

| Budget | Bounds |
|---|---|
| steps | a loop that makes progress but never converges |
| tokens | a loop that grows its own context until the window bursts |
| cost | the number finance asks about |
| seconds | the number the user experiences |

Budgets are checked **before** a step, not after. Learning you are over budget
after spending the money is an audit, not a budget.

The cost budget is optional because it needs a pricing catalog. A missing
catalog does not silently disable it — spend simply stays at zero and the
budget never fires, which is visible in the metrics rather than hidden.

## The final tool-free turn

Cutting a run dead at the ceiling leaves the user with nothing.

Instead, a budget stop triggers one last call with `tool_choice="none"` and a
message telling the model what happened and asking it to answer with what it
has. A partial answer naming the gap is almost always more useful than
silence, and much more useful than an answer that pretends the gap is not
there.

The cost of that last turn has to be inside the ceiling you chose, not on top
of it. And if a provider ignores `tool_choice="none"`, the trace records the
final turn with `ok=False` rather than letting an empty answer look like a
normal stop.

## Every tool call gets a result

Including refused ones, including timed-out ones.

An assistant turn that requested three calls and received two results leaves
the conversation in a shape most providers reject outright, and the ones that
accept it produce confused output. The loop makes half-turns impossible: it
walks the calls and the results together with `strict=True` and appends a
message for each.

Tool errors are fed back as data, with the error class and a correction
instruction. A model can only recover from an error it is shown. There is a
ceiling on total tool errors, because a model that cannot recover after four
tries will not recover after forty.

## Loop detection: warn, then stop

The failure this catches is specific: the agent calls `get_order(id=42)`,
dislikes the answer, and calls `get_order(id=42)` again. Nothing errors. Every
step looks healthy. The budget drains.

Detection reuses the tool layer's call signature, so argument reordering does
not disguise a repeat.

The response is graduated:

- **second occurrence** — a warning is injected *into the tool result*
- **third occurrence** — the run stops with `loop_detected`

Warning before stopping is the useful part. A model told "this call returned
the same result as before; try a different approach" frequently does try a
different approach and the run completes. Stopping at the second occurrence
kills runs that were about to recover; never stopping turns a stuck run into a
full budget burn.

The warning goes inside the tool result rather than into a separate system
message, because that is where the model is already looking.

## What loop detection costs, measured

Twenty scripted tasks, five of them stuck runs, under two configurations that
differ in exactly one way:

| Configuration | Completion | p50 steps | p95 steps | Loop rate |
|---|---|---|---|---|
| detection on | 75.0% | 2.0 | **3.0** | 25.0% |
| detection off | **100.0%** | 2.0 | 7.0 | 0.0% |

Read that carefully, because the naive reading is that detection made things
worse.

In these scripts the stuck runs recover on their own after six repeats. That
is an optimistic assumption — a real model may never recover — but it makes
the trade-off visible: **loop detection saves 4 steps at p95 and costs 25
percentage points of completion**, by cutting runs that would have found their
way out.

`stop_at` is the dial on that trade-off, and where to set it depends on
whether your steps are expensive or your completions are.

## Reading the metrics in the right order

1. **loop rate** — are runs getting stuck?
2. **budget stop rate** — are they being cut off?
3. **recovery rate** — do they survive a tool failure?

Loop rate first, because a loop inflates everything downstream: steps, cost,
and the budget stop rate. Tuning budgets while the loop rate is high just
raises the ceiling on wasted work.

Budget stop rate second. High with a low loop rate means the budget is
genuinely too tight; the same number with a high loop rate means it is doing
its job.

Recovery rate last, and it is the most interesting: the share of runs that hit
a tool error and still finished. A low recovery rate says the tool layer's
error messages are not actionable — a prompt and description problem, not a
budget one. Runs that never hit an error are excluded from the denominator;
including them would turn it into a measure of how rarely tools fail.

## Checkpoints and the guarantee's limit

`Thread.to_json()` and `Thread.from_json()`. Resuming is passing an existing
thread to `run()`, which is why checkpoint recovery is ordinary rather than
special-cased.

Side-effecting results are cached by call signature, so a resumed run that
replays a call gets the stored result instead of charging twice.

The window this does **not** close: the process can die after the tool ran and
before the checkpoint was written. Only an idempotent tool closes that. A
guarantee stated without its limit is worse than no guarantee, because
somebody will rely on it.

Approval works the same way. A run that hits `needs_approval` stops with the
call signature recorded; approving that signature and re-running the same
thread continues from where it stopped.
