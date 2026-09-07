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
