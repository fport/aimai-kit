# 5. Harness

The agent loop bounds a run. This layer makes a *long* run survivable, and
every piece of it exists because of a specific way long runs fail.

!!! done "What we built here"

    The segment model and a `ContextManager`, spill and a scratchpad for large
    tool output, threshold-triggered compaction with a versioned prompt, a
    SQLite memory store with a deterministic write gate, a schema-constrained
    sub-agent, and the two layers of isolation that can be written as code.

## The atomic unit of context is a segment

A tool call and its result are one thing.

Drop the result and keep the call, and the model is looking at a request that
was never answered. Drop the call and keep the result, and there is an answer
to a question nobody asked. Most providers reject the first shape outright.

So the unit that gets trimmed is a **segment**: one or more messages that live
or die together. Everything downstream — fill ratio, trim order, compaction —
operates on segments, and the pairing invariant is then free rather than
something each of them has to remember separately.

```python
from aimai_kit.harness import segments_from_messages

segments = segments_from_messages(thread.messages)
for s in segments:
    print(s.kind.value, len(s.messages), "droppable" if s.droppable else "FIXED")
# task 1 FIXED
# tool_turn 2 droppable      <- assistant turn + tool result, together
# tool_turn 2 droppable
# assistant 1 droppable
```

The prefix (system blocks, the original task) is marked non-droppable, which
is what makes "trim from the end" a safe rule rather than a hopeful one.

Keeping the original task is not a detail. An agent that forgets what it was
asked will confidently answer a different question, and that failure is
invisible in every metric except the answer itself.

## Trim from the end, always

Trimming from the middle of a conversation invalidates every cached token
after the cut. A trim that recovers 2,000 tokens can cost 40,000 in
reprocessing — the cache prefix is worth more than the tokens the trim
recovers.

So the oldest droppable segments go first, the prefix stays, and the most
recent turn stays. Without the last one the model has no idea what it was just
doing.

```python
from aimai_kit.harness import ContextManager

manager = ContextManager(window=200_000, output_reserve=4_000)
messages, stats = manager.build(thread.messages, step=thread.step)

print(stats.as_dict())
# {'step': 12, 'input_tokens': 148204, 'fill_ratio': 0.756,
#  'segments': 22, 'dropped_segments': 3, 'compacted': False}

print(manager.fill_percentile(95))   # 0.81
```

The fill ratio is recorded **every step**, not only when something goes wrong.
A run sitting at 0.92 for thirty steps has not failed; it is one long tool
result away from failing, and the only way to know that in advance is to have
been watching. A p95 fill ratio consistently above 0.9 means the budget is
wrong, not that the runs were unlucky.

## Spill: keep the information, lose the tokens

Truncation stops one result from filling the window. It does not solve the
underlying problem — the information is gone, and an agent that needed line
400 of a 900-line file cannot get it and does not know that it cannot.

Spilling keeps both properties. The full output goes to disk, the context gets
a short summary plus a `spill://` reference, and a tool lets the agent read
any line range of the original.

```python
from aimai_kit.harness import SpillStore, build_spill_tools

store = SpillStore(Path("runs/abc123"), threshold_chars=4_000)
summary = store.spill("find_orders", huge_output)
print(summary)
# [find_orders returned 25089 characters over 900 lines; the full output is
#  stored at spill://7e721695fa0a]
#
# First 600 characters:
# ...
#
# [use read_spill with ref=spill://7e721695fa0a and a line range to read any
#  part of the full output]

registry = ToolRegistry(build_spill_tools(store))
registry.names()   # ['read_notes', 'read_spill', 'write_note']
```

The summary is what makes this work. A bare reference forces the agent to read
the file just to decide whether reading it is worth it, which spends the
tokens the spill was supposed to save. So the summary states the size, the
line count, and the first few hundred characters.

The scratchpad is the same idea from the other direction: somewhere to put
intermediate findings that is not the context window, with a tool to write and
a tool to read back.

Spill files are grouped per run, because a run's spill files are garbage the
moment it ends and a directory is easier to delete than a query.

## Compaction: convert history instead of dropping it

Trimming loses information. Compaction converts it — the oldest segments are
replaced by one summary segment and the run continues with room to work.

Three decisions shape it:

**Threshold-triggered, not per-step.** Compacting every step spends a model
call to save tokens that were not scarce yet. The trigger is a fill ratio
*and* a minimum amount of history; compacting a short conversation spends a
call to summarize four turns into three.

```python
from aimai_kit.harness import Compactor

compactor = Compactor(client, registry, prompt_key="compaction@v2",
                      trigger_ratio=0.75, keep_recent=4)

if compactor.should_compact(stats.fill_ratio, segments):
    result = compactor.compact(segments)
    print(result.compacted_count, result.saved_tokens)
    # 14 41203
```

**Triggered at a step boundary.** A compaction in the middle of a tool turn
would separate a call from its result — the exact thing the segment model
exists to prevent.

**The prompt is a versioned file.** Compaction is a lossy transformation
applied to the agent's own memory, so "which version of the summarizer
produced this state?" has to be answerable. It goes through the same registry
as every other prompt and the summary segment records the `prompt_ref`.

The summary segment is itself droppable. Marking it permanent would make very
long runs impossible, because eventually the summaries fill the window.

## Needle tests, and why the compaction prompt is long

What must survive is stated explicitly in the prompt rather than left to the
model's judgment: decisions, constraints, numbers, open questions, failed
approaches, references. A summary that reads well and drops a number is worse
than no summary, because it looks trustworthy.

The needle test plants a known fact early in a conversation, buries it under
noise until compaction triggers, then checks whether the fact survived. Three
different needles — an identifier, an amount, a date — because a summarizer
that happens to keep one number is not the same as one that keeps numbers.

Both prompt versions are tested:

| Prompt | Order id | Amount | Date |
|---|---|---|---|
| `compaction@v1` ("keep it short") | lost | lost | lost |
| `compaction@v2` (names what must survive) | kept | kept | kept |

That comparison is the point. "We compact the context" is not a claim anyone
can act on; "v1 loses three of three planted facts and v2 loses none" says
which prompt to ship.

## Memory: a deterministic write gate

Three record types, because they answer different questions and expire
differently — episodic (what happened), semantic (what is true), procedural
(how to do something).

The write gate is **deterministic**, and that is the whole design. Asking the
model "should this be remembered?" produces a store that fills with the
model's own speculation, and speculation that has been written down reads
exactly like a fact on the way back out.

Rules decide instead:

```python
from aimai_kit.harness import MemoryStore, MemoryKind, WriteRefused

store = MemoryStore("memory.sqlite3")
store.write(MemoryKind.SEMANTIC,
            "Customer c-100 is on the enterprise tier.", source="crm")

for bad in [
    "Card 4111111111111111 is on file",
    "Contact is buyer@example.com",
    "The customer is probably unhappy",
    "The account is suspended right now",
]:
    try:
        store.write(MemoryKind.EPISODIC, bad, source="chat")
    except WriteRefused as e:
        print(e)
# not stored: looks like a credential or personal identifier
# not stored: looks like a credential or personal identifier
# not stored: reads as speculation rather than an observed fact
# not stored: phrased as something that is only true right now
```

Refused: anything matching credential or personal-identifier patterns;
anything phrased as transient ("right now", "currently"); anything phrased as
inference ("probably", "seems like"); anything too short to be useful on
recall.

The sensitive-pattern list is short and blunt on purpose. A gate that tries to
be clever about what counts as sensitive ends up with exceptions, and
exceptions are how secrets get stored.

`valid_until` exists because most memories are wrong eventually. "The customer
is on the trial plan" is true for thirty days and misleading afterwards.
Recall filters on it and the stale rate is published as a counter, so the
store's decay is visible rather than something users discover.

```python
store.write(MemoryKind.SEMANTIC, "Customer c-101 is on a trial plan.",
            source="crm", valid_until=date.today() - timedelta(days=1))

store.recall()                      # the stale record is filtered out
store.recall(include_stale=True)    # unless you ask for it
store.stale_ratio()                 # 0.25
```

## Sub-agents: delegate the reading

A task requiring thirty documents fills the main window with material needed
once. By document twenty the agent is compacting away its own findings.

A sub-agent runs the reading in its own thread with its own window and returns
a **schema-constrained** report. The main agent receives a summary and
citations, not the documents.

```python
from aimai_kit.harness import Subagent

sub = Subagent(client, executor, allowlist=["read_source"])
result = sub.run("Which order is affected?")

print(result.report.summary)      # "The affected order is ORD-88421."
print(result.report.evidence)     # ['ORD-88421']
print(result.report.confident)    # True
print(result.compression_ratio)   # 18.4  <- spent inside / returned outside
```

Constrained rather than free text for the same reason extraction is: a
sub-agent answering in prose gives the caller something to interpret rather
than something to use.

`evidence` is verified programmatically — every cited identifier must appear
in what the sub-agent actually saw. Unverifiable references are dropped and
confidence is lowered rather than the report being rejected, because a smaller
honest report is more useful than a failure. A citation nobody can resolve is
worse than admitting nothing was found.

The measure of whether delegation is working is the compression ratio: tokens
spent inside over tokens returned. A ratio near 1.0 means the sub-agent
returned everything it read, which is delegation in name only.

Only one level. A sub-agent cannot spawn a sub-agent. Nested delegation makes
cost and failure impossible to reason about, and every attempt to allow it
ends with a depth limit anyway.

## Isolation: three layers, one that matters

Tools run code, from a model, acting on arguments that may have come from a
document that came from anywhere.

| Layer | What it does | Where it lives |
|---|---|---|
| in-process | binary allowlist, path jail | `sandbox.py` |
| process | timeout, cleaned environment | `sandbox.py` |
| container | **no network**, resource limits | deployment |

Layer 3 is the one that matters, and closing the network is the single most
important decision in it. Layers 1 and 2 stop mistakes; a process with no
route out cannot exfiltrate anything even when they are defeated, because
there is nowhere to send it. Every other control degrades gracefully. Network
access does not — it is on or off.

```python
from aimai_kit.harness import Sandbox, SandboxViolation

sandbox = Sandbox(root=Path("runs/abc123/workspace"))

sandbox.run("cat notes.txt")           # fine
sandbox.run("curl https://evil.example")
# SandboxViolation: 'curl' is not on the allowlist (cat, grep, head, ls, tail, wc)

sandbox.resolve("../../etc/passwd")
# SandboxViolation: path '../../etc/passwd' resolves outside the sandbox root
```

Two details in the code are worth knowing. Paths are resolved **before** the
containment check, because `../../etc` passes a string comparison and then
escapes; resolving also follows symlinks, which closes the other obvious
route. And `shell=True` is never used: a shell turns one command into a
language with pipes, substitution and redirection, and an allowlist over a
language is not an allowlist.

## Three configurations, measured

The task: read thirty documents, one containing a fact the final answer needs.
The model is a stub that answers from what is actually in its context, so a
configuration that trimmed the fact away cannot answer and no prompt wording
hides it.

| Configuration | Steps | Total tokens | p95 fill | Answer survived |
|---|---|---|---|---|
| naive trim | 30 | 101,114 | 0.979 | no |
| compaction | 30 | 69,539 | 0.692 | no |
| compaction + sub-agent | 30 | **12,018** | **0.134** | **yes** |

Compaction cut tokens by 31% and the p95 fill ratio from 0.98 to 0.69 — a run
that was one long result away from bursting became one with headroom. It did
not save the answer.

One caveat that matters for reading the middle row honestly: in that run the
needle is sitting in a spill file, reachable with `read_spill`. The simulated
agent never follows the reference. So the row says "a spill summary plus
compaction is not enough *if the agent does not follow its references*",
which is a real failure mode and a different claim from "compaction does not
work".

The third row is the one with the lesson. Delegating the reading cut tokens by
88% and kept the answer, because the main context never held the documents in
the first place. The cheapest context management is not managing context you
never took on.
