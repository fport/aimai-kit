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
