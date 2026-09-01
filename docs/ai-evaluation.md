# AI Evaluation

Evaluation is layered after static validation. WorkflowGuard extracts a structured requirement spec from the prompt, maps workflow semantics from the canonical graph, then scores prompt alignment, reliability, security, and maintainability with explainable evidence.

AI providers are optional and provider-neutral. With `WORKFLOWGUARD_AI_PROVIDER=none`, deterministic extraction and analyzers still run. OpenAI and Groq can be enabled through environment variables. AI responses are schema-validated before use, and provider errors/timeouts/malformed output fall back to deterministic behavior.

## Reliability: declared vs measured

Reliability was originally a static score - it checked whether a node declared a timeout or
retry and whether an edge was labelled as an error path. That establishes intent, not
behaviour: a workflow could score 100 while dropping every failed record.

When a fuzz campaign exists for the workflow's current version, reliability becomes:

```
reliability = 0.6 x findings-based score + 0.4 x measured robustness
```

With no campaign the score is exactly what it was before, so existing workflows are unaffected
until they are fuzzed. A campaign where nothing was exercised does not blend either: a
robustness of 100 over zero cases means unmeasured, not robust, and crediting it would hand out
score for free.

Fuzz outcomes also emit `WG-FUZZ-001` to `WG-FUZZ-004` reliability findings, each carrying the
seed and case names needed to reproduce it. Those findings contribute penalties to the
findings-based term as well, so a fragile workflow is marked down on both - which is why the
stored calculation names that term `penalty_score` rather than claiming a fuzz-free baseline.

## Groq

`WORKFLOWGUARD_AI_PROVIDER=groq` enables Groq for requirement extraction, test generation,
repair, and fuzz-case generation. Set `WORKFLOWGUARD_AI_MODEL` to a Groq model id, for example
`openai/gpt-oss-120b`.

Structured output is requested as `json_schema` with `strict` on models that support it and
falls back to `json_object` otherwise. Model output is never trusted: proposed fuzz cases are
schema-validated, then unknown node ids, unknown failure types, and unbounded occurrence counts
are dropped before anything reaches the simulator.

AI cases are added to the deterministic corpus rather than replacing it. The deterministic
generator provides systematic coverage that a model will not reliably enumerate; the model
contributes attacks specific to what the workflow does.

