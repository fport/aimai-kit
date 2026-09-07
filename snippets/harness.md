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
