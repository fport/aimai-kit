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
