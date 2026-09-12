# AI Evaluation

Evaluation is layered after static validation. WorkflowGuard extracts a structured requirement spec from the prompt, maps workflow semantics from the canonical graph, then scores prompt alignment, reliability, security, and maintainability with explainable evidence.

AI providers are optional and provider-neutral. With `WORKFLOWGUARD_AI_PROVIDER=none`, deterministic extraction and analyzers still run. OpenAI and Groq can be enabled through environment variables. AI responses are schema-validated before use, and provider errors/timeouts/malformed output fall back to deterministic behavior.

## Requirement documents as part of the prompt

Requirements do not have to come from the upload form's prompt box. A BRD, PDD, or SDD can be
attached to a workflow, and its requirements are matched against the graph *alongside* the
prompt - both sources land in one `RequirementSpec`, and every `RequirementItem` records which
source it came from. Attachments are optional; a workflow with none scores exactly as before.

Documents are not fed through the prompt clause splitter. That splitter breaks on `[,;\n]`,
which on a real 2.8 KB BRD produced 70 "requirements" consisting largely of headings and
`**Sponsor:**` metadata lines. Instead `workflow_core/documents` walks the markdown structure:
`BR-n` / `Step n` / `x.y` sections become requirement groups, their bullets become atomic
clauses, decision-matrix tables become constraints, and integration tables become integration
requirements that name their own systems. Context sections - Business Context, Acceptance
Criteria, Data Fields, SLAs - are kept for display but never scored.

### Two matchers, two severities

Prompt requirements share vocabulary with node names, so token-overlap matching is fair
evidence there. Document requirements are written by an analyst who never saw the graph
("Verify business email domain against company registry" against a node named "Check Domain"),
so a keyword miss usually means the matcher failed, not that the behaviour is absent. When an
AI provider is configured it judges requirement/node correspondence directly and returns
verdicts with evidence; `WG-ALIGN-001` severity follows whoever decided:

| Requirement source | Judged by | `WG-ALIGN-001` |
| --- | --- | --- |
| prompt | deterministic | ERROR |
| prompt | ai | ERROR |
| document | ai | ERROR |
| document | deterministic | **WARNING** + a limitation saying why |

Without that split, attaching a BRD would report "your workflow is missing 40 requirements"
when what actually failed was string matching. On the ten reference workflows the deterministic
matcher's miss rate is about 15%, which at ERROR severity would floor the dimension on every
one of them.

### Ordering is not checked for documents

Document requirements never enter `required_order`. A document lists requirements in
presentation order - bullets inside a section, sections down the page - and that is not a
required execution sequence. Asserting a graph path between consecutive bullets produced 8
`WG-ALIGN-002` ordering errors against a single genuine miss on `C01`, flooring the dimension
for reasons that had nothing to do with alignment. Prompt ordering is unchanged.

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
are dropped before anything reaches the execution engine.

AI cases are added to the deterministic corpus rather than replacing it. The deterministic
generator provides systematic coverage that a model will not reliably enumerate; the model
contributes attacks specific to what the workflow does.

