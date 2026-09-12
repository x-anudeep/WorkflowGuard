# WorkflowGuard Architecture

## Scope

Part 1 established a production-oriented foundation for parsing, storing, validating, and visualizing workflow graphs. Part 2 added semantic evaluation and prompt alignment without changing the deterministic validation contract. Part 3 added automated workflow QA: test generation, safe simulation, assertions, failure injection, coverage, and persisted test history. Part 4 added cost intelligence, version comparison, and controlled AI-assisted repair. Part 5 completes the product shell with quality gates, reports, audit history, CI/CD examples, observability endpoints, demo assets, and dashboard/repository polish.

```mermaid
flowchart TD
  A[Human Requirement / Prompt] --> B[Human or AI Workflow]
  B --> C[Workflow Ingestion]
  C --> D[Format Parser]
  D --> E[Canonical Workflow Graph]
  E --> F[Static Validator]
  E --> G[Prompt Alignment Engine]
  E --> H[Semantic Evaluator]
  E --> I[Reliability Analyzer]
  E --> J[Security Analyzer]
  E --> K[Test Generator]
  K --> L[n8n Execution Engine]
  E --> M[Cost Intelligence]
  E --> N[Optimization Engine]
  H --> O[AI Repair Engine]
  F --> P[Quality Gate]
  G --> P
  L --> P
  M --> P
  P --> Q[Dashboard / CLI / CI]
  O --> R[Repair Candidate]
  R --> F
  R --> L
```

## Monorepo Layout

```text
apps/
  api/      FastAPI application, database models, migrations, REST endpoints
  web/      Next.js application, upload UI, dashboard, graph visualization
packages/
  workflow-core/  Canonical models, parsers, graph validation, requirement extraction, requirement documents, semantic evaluation, tests, n8n emitter and execution engine, costing, comparison, repair, CLI
examples/   Supported and intentionally broken workflow fixtures
docs/       Architecture and operating notes
docker/     Service Dockerfiles
```

## Canonical Workflow Representation

Supported source formats are BPMN, n8n, qubi flow exports, and a generic JSON schema. Every one converts into a `Workflow` with:

- stable workflow metadata, source format, source type, optional source prompt
- typed `Node` records with provider-specific configuration and preserved metadata
- typed `Edge` records with source/target references, labels, optional conditions, and metadata
- variables reserved for future workflow engines and test generation

The canonical model is intentionally engine-neutral. Parser-specific data is stored in `metadata` and `configuration` so future analyzers can reason over native details without polluting the common graph contract.

## Parser Architecture

Parsers implement:

- `supports(filename, content, content_type)`
- `validate_source(content)`
- `parse(filename, content, source_type, source_prompt, content_type)`

`ParserRegistry` owns detection and dispatch. Adding UiPath, Temporal, Airflow, LangGraph, Make, Zapier, or additional engines should require a new parser class and registration, not changes to validation rules or API persistence.

## Static Validation

The validation engine builds a NetworkX directed graph from the canonical model, then applies independent rules. Each rule returns structured findings with severity, rule ID, affected node/edge, explanation, and remediation.

The initial Structural Quality Score is deterministic and based on findings plus detectable configuration completeness. It is deliberately separate from future AI quality dimensions.

## Semantic Evaluation

Semantic evaluation is a second layer, not a replacement for static validation. It produces an Overall Workflow Score with dimension scores:

- Structural Validity
- Prompt Alignment
- Reliability
- Security
- Maintainability

The evaluation engine uses:

- deterministic requirement extraction as a baseline
- optional AI-assisted requirement extraction through a provider-neutral interface
- attached requirement documents (BRD/PDD/SDD) parsed by `workflow_core/documents` and merged into the same spec, tagged with their provenance
- optional AI-assisted requirement *matching*, used for document requirements whose business vocabulary keyword matching cannot bridge
- schema validation for every AI-produced `RequirementSpec`
- canonical graph matching for required actions, ordering, conditions, approvals, integrations, and outputs
- deterministic security, reliability, and maintainability analyzers

Every evaluation finding is explainable: expected behavior, observed behavior, reason, location, remediation, and confidence.

## AI Provider Boundary

The API owns provider adapters. The core evaluation and testing engines do not depend on an AI vendor. `WORKFLOWGUARD_AI_PROVIDER=none` runs the system in deterministic mode. `openai` and `groq` can be configured with `WORKFLOWGUARD_AI_API_KEY`, `WORKFLOWGUARD_AI_MODEL`, and `WORKFLOWGUARD_AI_TIMEOUT_SECONDS`. Groq is used through its OpenAI-compatible chat-completions endpoint and covers requirement extraction, requirement matching, test generation, repair, and fuzz-case generation.

Provider timeouts, malformed responses, credential failures, rate limits, and request errors are handled gracefully and fall back to deterministic requirement extraction, deterministic test generation, and deterministic repair patches. Raw model output is never trusted or stored without schema validation.

## Workflow QA

Part 3 introduces `workflow_core.testing`:

- `WorkflowTest`: reusable tests with input data, mocks, failure injection, expected path/output/side effects, assertions, tags, importance, rationale, and linked requirements
- `DeterministicTestGenerator`: graph- and requirement-driven generation for happy paths, branches, edge cases, dependency failures, LLM failure modes, and adversarial prompt-injection cases
- `N8nEmitter`: compiles a canonical workflow into an n8n workflow. Gateways become real IF/Switch nodes; a node that must branch but cannot gets a synthetic router behind it; failure edges map onto n8n's error output. Every integration node's URL is rewritten to the mock server, so an emitted workflow carries no credentials and cannot reach a real service
- `N8nExecutionEngine`: publishes each compiled workflow once, triggers it per test, and reads the execution back. Bounded at both ends - n8n stops a run at the workflow's `executionTimeout`, and results are truncated at 250 steps - so a cyclic uploaded workflow cannot exhaust the engine
- `map_execution`: rebuilds a `SimulationResult` in canonical node and edge ids, so assertions and coverage are unchanged by the move to real execution
- `AssertionEngine`: extensible assertions for executed nodes/edges, outputs, errors, retries, approvals, external calls, and successful termination
- `CoverageCalculator`: workflow coverage across nodes, edges, branches, and requirements
- `WorkflowTestRunner`: combines execution, assertions, status calculation, duration, failures, and coverage contribution. An unreachable engine is recorded as such rather than as a workflow defect

External integrations are mocked by default. Failure injection models timeouts, rate limits, HTTP 500s, authorization errors, unavailable dependencies, and malformed LLM output without calling real services or executing uploaded code.

## Requirement Documents

`workflow_core/documents` turns an attached BRD, PDD, or SDD into atomic requirement clauses by
walking the markdown structure rather than splitting on punctuation - headings become sections,
`BR-n` / `Step n` / `x.y` subtrees are scored, context sections are not, decision tables become
constraints, and integration tables name their own systems. Clauses are parsed once at upload
and stored on `workflow_attachments`, so a parser change cannot silently move an existing
workflow's score without a re-upload.

## Fuzz Testing

`workflow_core.fuzzing` measures error handling rather than inferring it:

- `DeterministicFuzzGenerator`: seeded, reproducible corpus of input mutations and dependency-failure scenarios
- `FuzzEngine`: executes cases through the engine in failure-propagating mode and classifies each outcome as handled, silently swallowed, crashed, hung, or not triggered
- `fuzz_findings`: `WG-FUZZ-001` to `WG-FUZZ-004` reliability findings carrying reproduction seeds
- `robustness_score`: share of exercised cases the workflow survived

`workflow_core.analysis.failure_paths` decides whether an edge is an error path, using whole-word matching on human labels and polarity-aware analysis on branch expressions, so `result.success == false` is recognised as a failure path while `result.success == true` is not.

Fuzz results are persisted as `fuzz_runs` / `fuzz_cases` and blended into the reliability dimension. See `docs/ai-evaluation.md`.

The `workflowguard` CLI exposes `validate`, `evaluate`, `fuzz`, and `test` commands with stable exit codes for future GitHub Actions use.

## Cost Intelligence

Part 4 introduces `workflow_core.costing`:

- `PricingEntry`: editable/versioned pricing assumptions with provider, model, effective date, unit costs, currency, source, and metadata
- `CostScenario`: executions/day or month, payload size, token estimates, and failure/retry rate
- `CostEstimator`: per-node and per-run estimates, projected daily/monthly/annual totals, and line-item pricing assumptions
- `CostOptimizationEngine`: deterministic optimization findings for repeated LLM calls, expensive models used for simple tasks, duplicate API calls, excessive retries, and large repeated model context

Pricing seed data is deliberately labeled as a development assumption. It is not hardcoded into estimation logic; API persistence can store updated catalog entries.

## Version Comparison

`workflow_core.comparison` compares canonical workflow versions for added/removed nodes, added/removed edges, configuration changes, and score/cost/coverage deltas where the API has stored history. Repair acceptance uses this mechanism to make behavior changes visible.

## Repair

Part 4 introduces `workflow_core.repair` and API repair services:

- AI repair providers generate schema-validated `RepairPatch` objects.
- Deterministic repair fallback proposes bounded timeout/retry configuration.
- Patches apply only to an in-memory candidate for preview.
- Preview runs static validation, semantic evaluation, generated tests, and cost estimation.
- Accepting a proposal creates a new workflow version; rejecting keeps history without mutating the workflow.

Safety checks flag new external destinations, approval removal, and node removal. Uploaded source files and existing tests are not rewritten or deleted.

## Persistence

PostgreSQL stores:

- workflows
- workflow versions
- raw uploaded files
- canonical nodes
- canonical edges
- validation runs
- validation findings
- requirement specifications
- evaluation runs
- evaluation findings
- dimension scores
- workflow tests
- workflow test runs
- fuzz runs
- fuzz cases
- pricing catalog
- cost scenarios
- cost estimates
- optimization findings
- repair proposals
- repair validation results
- quality gate runs
- audit events

The schema leaves room for future tables such as execution logs, observability events, alerts, and deployment environments.

## API

FastAPI exposes upload, filtered list, detail, graph, validation, semantic evaluation, requirements, test generation, test creation, test execution, test history, pricing, cost estimation, version comparison, repair proposal/accept/reject, quality gates, history, reports, versions, dashboard, health, readiness, and metrics endpoints under `/api`. OpenAPI docs are generated automatically at `/docs`.

## Frontend

The Next.js UI is a developer-tool surface:

- Dashboard uses real backend metrics.
- Upload supports drag/drop, source type, and original prompt capture.
- Workflow detail shows overview, React Flow graph, validation findings, canonical source, and version context.
- Workflow detail shows AI Evaluation with overall/dimension scores, requirement-vs-implementation evidence, grouped findings, and evaluation history.
- Workflow detail shows Tests with generation/run controls, total/pass/fail/coverage metrics, generated-test rationale, and stored execution traces.
- Workflow detail shows Cost, Versions / Compare, and Repair panels with scenario controls, line-item assumptions, optimization findings, version diffs, patch previews, safety flags, and accept/reject actions.
- Node type styling distinguishes triggers, actions, conditions, LLMs, human approvals, external APIs, database nodes, and end nodes.

## Security Posture

Part 1 validates extensions and size, parses XML with entity resolution and network access disabled, and uses safe JSON decoding. Uploaded content is not executed during parsing or validation; what happens when a *test* runs it is set out under Security Posture below. Secrets are kept out of source and documented via `.env.example`.

Part 2 adds static security findings for embedded credentials, secret-like values, unsafe HTTP endpoints, missing auth configuration, and potential LLM sensitive-data exposure. These checks are explicitly best-effort and do not claim complete security coverage.

Workflow tests now execute for real, in n8n, and the containment moved with them.

- **No emitted workflow can reach a real service.** Every `external_api`, `database`, `email`
  and `llm` node has its URL rewritten to WorkflowGuard's own `/mock/{run}/{node}` endpoints.
  A request's method, headers and body are reproduced faithfully so a report can show what the
  workflow *would* have sent; the destination it declared is recorded in the body and never
  used. Emitted workflows carry no credentials.
- **Uploaded JavaScript is executed, under containment.** Skipping it did not make a run
  incomplete so much as unreliable: a Branch downstream of a Code node that never ran takes an
  arbitrary path, and the run then reports a confident verdict about something it never
  evaluated. So Qubi `Code` nodes run, in an **external task runner** - a separate process from
  n8n, on an `internal` Docker network with no route off the host, under a ten-second task
  timeout and container CPU and memory limits. A snippet that hangs, crashes or allocates
  takes the runner down, not the engine every other test is running in, and it cannot call out.
  Python `Code` nodes and BPMN `scriptTask`s are still not executed, and say so on the run.
- **A runaway workflow cannot exhaust the engine.** The simulator stopped at 250 steps; n8n has
  no step limit, so a cyclic workflow would run until it ran out of memory - an uploaded file
  denying service to the engine shared by every other run. Emitted workflows carry an
  `executionTimeout`, and results are truncated at the same 250 steps.
- **Runs are isolated from each other.** Each gets its own webhook path and its own namespace of
  mock endpoints, so concurrent runs cannot read each other's responses. Published workflows are
  deleted in a `finally`, with a sweep of `wg-` prefixed workflows as the backstop.
- **Approximations are declared, not hidden.** Anything the engine could not reproduce - an
  unmodelled node body, an auto-answered approval, a construct n8n cannot express - is recorded
  on the run and shown in the Tests panel, so a green run never implies work that was not done.

Part 4 repair is sandboxed at the canonical graph level: model output cannot overwrite stored source files or mutate current versions directly. Accepted proposals create new versions after preview.
