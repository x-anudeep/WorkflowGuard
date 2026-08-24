# WorkflowGuard Architecture

## Scope

Part 1 established a production-oriented foundation for parsing, storing, validating, and visualizing workflow graphs. Part 2 adds semantic evaluation and prompt alignment without changing the deterministic validation contract. It still does not implement repair, execution simulation, generated tests, or cost analysis.

## Monorepo Layout

```text
apps/
  api/      FastAPI application, database models, migrations, REST endpoints
  web/      Next.js application, upload UI, dashboard, graph visualization
packages/
  workflow-core/  Canonical models, parsers, graph validation, requirement extraction, semantic evaluation, scoring
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

The API owns provider adapters. The core evaluation engine does not depend on an AI vendor. `WORKFLOWGUARD_AI_PROVIDER=none` runs the system in deterministic mode. `openai` can be configured with `WORKFLOWGUARD_AI_API_KEY`, `WORKFLOWGUARD_AI_MODEL`, and `WORKFLOWGUARD_AI_TIMEOUT_SECONDS`.

Provider timeouts, malformed responses, credential failures, rate limits, and request errors are handled gracefully and fall back to deterministic requirement extraction. Raw model output is never trusted or stored without schema validation.

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

The schema leaves room for future tables such as generated tests, test runs, cost estimates, execution logs, and AI repairs.

## API

FastAPI exposes upload, list, detail, graph, validation, semantic evaluation, requirement, versions, dashboard, and health endpoints under `/api`. OpenAPI docs are generated automatically at `/docs`.

## Frontend

The Next.js UI is a developer-tool surface:

- Dashboard uses real backend metrics.
- Upload supports drag/drop, source type, and original prompt capture.
- Workflow detail shows overview, React Flow graph, validation findings, canonical source, and version context.
- Workflow detail shows AI Evaluation with overall/dimension scores, requirement-vs-implementation evidence, grouped findings, and evaluation history.
- Node type styling distinguishes triggers, actions, conditions, LLMs, human approvals, external APIs, database nodes, and end nodes.

## Security Posture

Part 1 validates extensions and size, parses XML with entity resolution and network access disabled, uses safe JSON decoding, and never executes uploaded content. Secrets are kept out of source and documented via `.env.example`.

Part 2 adds static security findings for embedded credentials, secret-like values, unsafe HTTP endpoints, missing auth configuration, and potential LLM sensitive-data exposure. These checks are explicitly best-effort and do not claim complete security coverage.
