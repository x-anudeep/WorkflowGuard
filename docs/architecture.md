# WorkflowGuard Architecture

## Scope

Part 1 established a production-oriented foundation for parsing, storing, validating, and visualizing workflow graphs. Part 2 added semantic evaluation and prompt alignment without changing the deterministic validation contract. Part 3 adds automated workflow QA: test generation, safe simulation, assertions, failure injection, coverage, and persisted test history. It still does not implement repair, cost analysis, or runtime observability ingestion.

## Monorepo Layout

```text
apps/
  api/      FastAPI application, database models, migrations, REST endpoints
  web/      Next.js application, upload UI, dashboard, graph visualization
packages/
  workflow-core/  Canonical models, parsers, graph validation, requirement extraction, semantic evaluation, tests, simulator, CLI
examples/   Supported and intentionally broken workflow fixtures
docs/       Architecture and operating notes
docker/     Service Dockerfiles
```

## Canonical Workflow Representation

Every supported source format converts into a `Workflow` with:

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
- schema validation for every AI-produced `RequirementSpec`
- canonical graph matching for required actions, ordering, conditions, approvals, integrations, and outputs
- deterministic security, reliability, and maintainability analyzers

Every evaluation finding is explainable: expected behavior, observed behavior, reason, location, remediation, and confidence.

## AI Provider Boundary

The API owns provider adapters. The core evaluation and testing engines do not depend on an AI vendor. `WORKFLOWGUARD_AI_PROVIDER=none` runs the system in deterministic mode. `openai` can be configured with `WORKFLOWGUARD_AI_API_KEY`, `WORKFLOWGUARD_AI_MODEL`, and `WORKFLOWGUARD_AI_TIMEOUT_SECONDS`.

Provider timeouts, malformed responses, credential failures, rate limits, and request errors are handled gracefully and fall back to deterministic requirement extraction and deterministic test generation. Raw model output is never trusted or stored without schema validation.

## Workflow QA

Part 3 introduces `workflow_core.testing`:

- `WorkflowTest`: reusable tests with input data, mocks, failure injection, expected path/output/side effects, assertions, tags, importance, rationale, and linked requirements
- `DeterministicTestGenerator`: graph- and requirement-driven generation for happy paths, branches, edge cases, dependency failures, LLM failure modes, and adversarial prompt-injection cases
- `WorkflowSimulator`: safe canonical-graph runtime that uses controlled adapters for trigger, transform/action, condition, LLM, HTTP/API, database, human approval, email, generic action, and end nodes
- `AssertionEngine`: extensible assertions for executed nodes/edges, outputs, errors, retries, approvals, external calls, and successful termination
- `CoverageCalculator`: workflow coverage across nodes, edges, branches, and requirements
- `WorkflowTestRunner`: combines simulation, assertions, status calculation, duration, failures, and coverage contribution

External integrations are mocked by default. Failure injection models timeouts, rate limits, HTTP 500s, authorization errors, unavailable dependencies, and malformed LLM output without calling real services or executing uploaded code.

The `workflowguard` CLI exposes `validate`, `evaluate`, and `test` commands with stable exit codes for future GitHub Actions use.

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

The schema leaves room for future tables such as cost estimates, execution logs, observability events, and AI repairs.

## API

FastAPI exposes upload, list, detail, graph, validation, semantic evaluation, requirements, test generation, test creation, test execution, test history, versions, dashboard, and health endpoints under `/api`. OpenAPI docs are generated automatically at `/docs`.

## Frontend

The Next.js UI is a developer-tool surface:

- Dashboard uses real backend metrics.
- Upload supports drag/drop, source type, and original prompt capture.
- Workflow detail shows overview, React Flow graph, validation findings, canonical source, and version context.
- Workflow detail shows AI Evaluation with overall/dimension scores, requirement-vs-implementation evidence, grouped findings, and evaluation history.
- Workflow detail shows Tests with generation/run controls, total/pass/fail/coverage metrics, generated-test rationale, and stored execution traces.
- Node type styling distinguishes triggers, actions, conditions, LLMs, human approvals, external APIs, database nodes, and end nodes.

## Security Posture

Part 1 validates extensions and size, parses XML with entity resolution and network access disabled, uses safe JSON decoding, and never executes uploaded content. Secrets are kept out of source and documented via `.env.example`.

Part 2 adds static security findings for embedded credentials, secret-like values, unsafe HTTP endpoints, missing auth configuration, and potential LLM sensitive-data exposure. These checks are explicitly best-effort and do not claim complete security coverage.

Part 3 simulation remains sandboxed at the model level: it never executes uploaded scripts, expressions, or workflow-engine runtime code. External systems are represented through mocks and failure injections.
