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
