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
