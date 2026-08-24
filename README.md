# WorkflowGuard

WorkflowGuard is an AI-powered verification, testing, evaluation, cost-analysis, and observability platform for human-created and AI-generated workflows.

Part 1 built the deterministic foundation: upload BPMN 2.0 XML, generic JSON, or n8n JSON; parse into a canonical workflow graph; run static validation; persist versions and findings; inspect results in a developer-tool UI.

Part 2 adds the intelligence layer: prompt-to-requirement extraction, semantic prompt alignment, explainable scoring, reliability analysis, security analysis, maintainability analysis, and persisted evaluation history.

Part 3 turns WorkflowGuard into an automated workflow QA system: deterministic and optional AI-assisted test generation, safe workflow simulation, assertions, failure injection, coverage calculation, test history, UI reporting, and CI-friendly CLI commands.

## Architecture

- `packages/workflow-core`: canonical workflow models, parser plugins, graph construction, validation rules, requirement extraction, semantic evaluation, generated tests, simulator, assertions, coverage, scoring, and CLI.
- `apps/api`: FastAPI, SQLAlchemy, Alembic, PostgreSQL persistence, upload/evaluation/test handling, REST API, provider-neutral AI adapters.
- `apps/web`: Next.js, TypeScript, Tailwind CSS, React Flow dashboard, upload, validation, evaluation, and workflow testing UI.
- `examples`: valid and intentionally broken BPMN, generic JSON, and n8n workflows.
- `docs`: architecture notes and roadmap context.

## Quick Start

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- Web: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/api/health`

If ports are already in use, run for example `API_PORT=18000 WEB_PORT=3100 docker compose up --build` and use `http://localhost:18000/api` plus `http://localhost:3100`.

## Local Backend

```bash
pip install -e packages/workflow-core -e apps/api[dev]
cd apps/api
alembic upgrade head
uvicorn workflowguard_api.main:app --reload
```

Set `WORKFLOWGUARD_DATABASE_URL` if you are not using the default local PostgreSQL connection.

## Local Frontend

```bash
npm install
npm run web:dev
```

`NEXT_PUBLIC_API_BASE_URL` defaults to `http://localhost:8000/api`.

## Tests

```bash
pip install -e packages/workflow-core -e apps/api[dev]
pytest packages/workflow-core/tests apps/api/tests
npm install
npm run web:test
npm run web:lint
npm run web:build
```

## CLI

Install the core package locally, then use the `workflowguard` command in CI or local scripts:

```bash
pip install -e packages/workflow-core
workflowguard validate examples/json/valid-workflow.json
workflowguard evaluate examples/json/valid-workflow.json --prompt "Approve requests, then notify Slack."
workflowguard test examples/json/valid-workflow.json --json
```

Exit codes:

- `0`: command completed successfully and quality gates passed
- `1`: workflow parsed but validation/evaluation/tests failed the command gate
- `2`: file could not be read or parsed

## Supported Formats

- BPMN 2.0 XML: `.bpmn`, `.xml`
- Generic Workflow JSON: `.json` with `nodes[]` and optional `edges[]`
- n8n JSON: `.json` with `nodes[]` and `connections{}`

The parser registry detects the correct parser automatically. Future parsers can implement the same `WorkflowParser` interface and register without changing the validation engine.

## Static Validation

Part 1 rules detect malformed sources, schema errors, duplicate node IDs, invalid edge references, missing starts/terminals, unreachable nodes, orphan nodes, dead-end paths, suspicious cycles, disconnected components, missing configuration, and empty conditions.

Findings use severities: `INFO`, `WARNING`, `ERROR`, `CRITICAL`.

The score shown in the UI is explicitly a deterministic **Structural Quality Score**, not an AI quality score.

## Semantic Evaluation

Semantic evaluation is separate from static validation. WorkflowGuard first uses deterministic parsing and graph rules, then evaluates prompt alignment and risk dimensions:

- Overall Workflow Score
- Structural Validity
- Prompt Alignment
- Reliability
- Security
- Maintainability

The evaluation response includes evidence for each important finding:

- what was expected
- what was found
- why it matters
- affected node, edge, or path where detectable
- suggested correction
- confidence

When no AI provider is configured, WorkflowGuard still runs deterministic requirement extraction and all deterministic analyzers. No paid API call is required for normal development or tests.

## AI Provider Configuration

The backend uses provider-neutral requirement extraction and test-generation interfaces. The default is disabled:

```bash
WORKFLOWGUARD_AI_PROVIDER=none
```

To use OpenAI for structured requirement extraction:

```bash
WORKFLOWGUARD_AI_PROVIDER=openai
WORKFLOWGUARD_AI_API_KEY=...
WORKFLOWGUARD_AI_MODEL=gpt-4o-mini
WORKFLOWGUARD_AI_TIMEOUT_SECONDS=20
```

AI requirement responses are validated against the `RequirementSpec` schema before use. AI-generated tests are validated against the `TestGenerationResult`/`WorkflowTest` schemas before storage. Provider errors, timeouts, malformed output, rate limits, and missing credentials fall back to deterministic generation.

## Workflow Testing

Workflow tests are first-class records. A test can store input data, mocked integrations, failure injections, expected paths, expected outputs, expected or forbidden side effects, assertions, tags, importance, generation source, rationale, and linked requirement IDs.

Generated suites include:

- happy path coverage
- conditional branch tests
- boundary, null, missing field, incorrect type, malformed input, and duplicate event cases
- dependency failure injection for API/database/LLM nodes
- HTTP timeout, HTTP 429, HTTP 500, authorization, unavailable dependency, retry exhaustion-style checks
- prompt-injection defensive tests for LLM workflows
- requirement-linked tests when a source prompt or requirement spec is available

The simulator never executes uploaded workflow code. It walks the canonical graph with controlled node adapters and mocks external systems by default. Test runs store execution order, branch decisions, external calls, retries, failures, duration, token estimates, assertion results, and coverage.

Coverage is workflow coverage, not source-code coverage:

- Node Coverage
- Edge Coverage
- Branch Coverage
- Requirement Coverage
- Overall Test Coverage

## Important Endpoints

- `POST /api/workflows`
- `POST /api/workflows/upload`
- `GET /api/workflows`
- `GET /api/workflows/{id}`
- `GET /api/workflows/{id}/versions`
- `POST /api/workflows/{id}/validate`
- `GET /api/workflows/{id}/validation`
- `GET /api/workflows/{id}/graph`
- `POST /api/workflows/{id}/evaluate`
- `GET /api/workflows/{id}/evaluations`
- `GET /api/workflows/{id}/evaluations/{evaluation_id}`
- `GET /api/workflows/{id}/requirements`
- `POST /api/workflows/{id}/tests/generate`
- `POST /api/workflows/{id}/tests`
- `GET /api/workflows/{id}/tests`
- `POST /api/workflows/{id}/tests/run`
- `POST /api/tests/{test_id}/run`
- `GET /api/workflows/{id}/test-runs`
- `GET /api/test-runs/{id}`
- `GET /api/dashboard`

## Environment Variables

- `WORKFLOWGUARD_DATABASE_URL`
- `WORKFLOWGUARD_CORS_ORIGINS`
- `NEXT_PUBLIC_API_BASE_URL`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `WORKFLOWGUARD_AI_PROVIDER`
- `WORKFLOWGUARD_AI_API_KEY`
- `WORKFLOWGUARD_AI_MODEL`
- `WORKFLOWGUARD_AI_TIMEOUT_SECONDS`

## Current Limitations

- Simulation is intentionally safe and adapter-based; it does not execute native workflow engine code or call real external services.
- Generated tests are reviewable starting points, not trusted truth.
- Semantic evaluation is static and best-effort; it does not prove runtime correctness.
- The deterministic requirement extractor is intentionally conservative and can miss nuanced requirements without an AI provider.
- No AI repair, cost estimation, production execution logging, or observability ingestion yet.
- BPMN diagram rendering is not enabled in the UI yet, but BPMN metadata is preserved for adding `bpmn-js`.
- Authentication and multi-user project isolation are intentionally deferred.

## Roadmap

Part 4 should add cost estimation, runtime/log observability ingestion, historical trend analysis, and deeper reporting based on validation, evaluation, and test-run history.
