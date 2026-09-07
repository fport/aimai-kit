- [ ] **The schema is strict**: `additionalProperties: false`, every field `required`,
      optionals expressed as `anyOf: [type, null]`.
- [ ] **Known value sets are `Literal`, not free text.** This is an accuracy change,
      not a validation change — free text invents its own vocabulary.
- [ ] **Money is integer minor units.** As a float, "1,250,000.50" arrives in more
      shapes than you want to parse.
- [ ] **Field descriptions are written as instructions to the model**, not as
      documentation for a reader. They are the part the model actually obeys.
- [ ] **The repair loop is bounded** at two or three attempts. Unbounded, a bad prompt
      becomes a bill.
- [ ] **Repair errors are readable.** A raw `ValidationError` repr is not a message a
      model can act on.
- [ ] **The mean attempt count is alarmed on.** Near 1.0 the schema fits; drifting
      toward the ceiling means the prompt or the schema is wrong, and the loop is
      hiding it.
- [ ] **Citations are verified against the source.** A schema validates shape, never
      content — a well-formed citation to a document that does not say that is exactly
      what a model produces under pressure.
