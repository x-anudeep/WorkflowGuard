# WorkflowGuard

WorkflowGuard is an AI-powered verification, testing, evaluation, cost-analysis, and observability platform for human-created and AI-generated workflows.

Part 1 built the deterministic foundation: upload BPMN 2.0 XML, generic JSON, or n8n JSON; parse into a canonical workflow graph; run static validation; persist versions and findings; inspect results in a developer-tool UI.

Part 2 adds the intelligence layer: prompt-to-requirement extraction, semantic prompt alignment, explainable scoring, reliability analysis, security analysis, maintainability analysis, and persisted evaluation history.

Part 3 turns WorkflowGuard into an automated workflow QA system: deterministic and optional AI-assisted test generation, real workflow execution in n8n, assertions, failure injection, coverage calculation, test history, UI reporting, and CI-friendly CLI commands.

Part 4 adds cost intelligence and controlled repair: configurable pricing, scenario forecasts, optimization recommendations, workflow version comparison, AI-assisted repair patch generation, sandbox preview, and accept/reject versioning.

Part 5 completes the demo-quality platform shell: quality gates, global repository filtering, audit/history, report export, dashboard charts, request IDs, readiness/metrics endpoints, GitHub Actions integration, and the invoice-processing demo project.

## Architecture

- `packages/workflow-core`: canonical workflow models, parser plugins, graph construction, validation rules, requirement extraction, semantic evaluation, generated tests, the n8n emitter and execution engine, assertions, coverage, cost estimation, version comparison, repair patches, scoring, and CLI.
- `apps/api`: FastAPI, SQLAlchemy, Alembic, PostgreSQL persistence, upload/evaluation/test/cost/repair handling, REST API, provider-neutral AI adapters, and the mock endpoints emitted workflows call instead of their real integrations.
- `apps/web`: Next.js, TypeScript, Tailwind CSS, React Flow dashboard, upload, validation, evaluation, testing, cost, compare, and repair UI.
- `examples`: valid and intentionally broken BPMN, generic JSON, and n8n workflows.
- `docs`: architecture notes and roadmap context.

## Quick Start

```bash
cp .env.example .env
docker compose up --build
```

Then open:

- Web: `http://localhost:3000`
- n8n: `http://localhost:5678` (create an API key at Settings > n8n API, or run
  `python scripts/bootstrap_n8n.py`, and set `WORKFLOWGUARD_N8N_API_KEY`; it needs the
  `workflow:activate` scope or publishing fails with a bare 403)
- API docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/api/health`

If ports are already in use, run for example `API_PORT=18000 WEB_PORT=3100 docker compose up --build` and use `http://localhost:18000/api` plus `http://localhost:3100`.

## Public API

The backend is a plain HTTP API and is usable directly, without the frontend.

- Base URL: `https://workflowguard-api.vercel.app/api`
- OpenAPI schema: `GET /api/openapi.json`
- Interactive docs: `https://workflowguard-api.vercel.app/docs`

```bash
curl https://workflowguard-api.vercel.app/api/health
curl https://workflowguard-api.vercel.app/api/workflows

curl -X POST https://workflowguard-api.vercel.app/api/workflows/upload \
  -F "file=@examples/bpmn/valid-workflow.bpmn" \
  -F "source_type=ai_generated"
```

Two things to know before building against it:

- **It is unauthenticated.** There are no API keys and no per-caller scoping, so
  every workflow is visible and modifiable by anyone with the URL. Do not put
  anything sensitive in it. Authentication is planned.
- **Requests and responses are limited to 4.5 MB**, and analysis endpoints run
  synchronously with a 300s ceiling. See [docs/vercel.md](docs/vercel.md).

## Hosting

WorkflowGuard should be hosted as four resources: the Next.js frontend, the FastAPI backend, PostgreSQL for durable workflow data, and an n8n instance that executes workflow tests.

**n8n must be reachable from the API, and the API from n8n.** Tests are compiled into n8n
workflows and really executed; their integration calls are redirected back at the API's
`/mock` endpoints, so the two talk in both directions. This also means the API cannot run more
than one worker while a test executes - a run opened in one worker is invisible to another.

This repo includes a Render Blueprint:

```bash
render.yaml
```

It creates:

- `workflowguard-web`: frontend
- `workflowguard-api`: backend
- `workflowguard-db`: PostgreSQL database

The API runs Alembic migrations before startup. Uploaded workflows, workflow versions, validation/evaluation/test/cost/repair records, and audit history are stored in PostgreSQL. The frontend stores no durable workflow data.

See [docs/deployment.md](docs/deployment.md) for the full deployment guide.

## Local Backend

```bash
pip install -e packages/workflow-core -e apps/api[dev]
cd apps/api
alembic upgrade head
uvicorn workflowguard_api.main:app --reload
```

Set `WORKFLOWGUARD_DATABASE_URL` if you are not using the default local PostgreSQL connection.

**Running tests needs n8n.** Upload, validation, evaluation, cost and comparison work without
it; anything that *executes* a workflow -- test runs, fuzz campaigns, repair validation -- needs
a reachable instance:

```bash
docker compose up -d n8n
python scripts/bootstrap_n8n.py --base-url http://localhost:5678   # prints N8N_API_KEY=...
export WORKFLOWGUARD_N8N_BASE_URL=http://localhost:5678
export WORKFLOWGUARD_N8N_API_KEY=...
export WORKFLOWGUARD_MOCK_BASE_URL=http://localhost:8000/mock
```

The key needs the `workflow:activate` scope, or publishing fails with a bare `403`.
`WORKFLOWGUARD_MOCK_BASE_URL` must be an address **n8n can reach**: n8n calls it back during a
run to serve the mocked integrations. That also means the API cannot run more than one worker
while a test executes -- the run's state lives in the process n8n calls back into.

## Local Frontend

```bash
npm install
npm run web:dev
```

`NEXT_PUBLIC_API_BASE_URL` defaults to `http://localhost:8000/api`. On the Vercel
deployment it is set to the relative path `/api`, so browser calls stay same-origin;
see [docs/vercel.md](docs/vercel.md).

## Tests

The suite is split by whether a test executes a workflow.

```bash
pip install -e packages/workflow-core -e apps/api[dev]
pytest packages/workflow-core/tests apps/api/tests -m "not integration"
npm install
npm run web:test
npm run web:lint
npm run web:build
```

Tests that really run a workflow are marked `integration` and skip unless an engine is
configured. They cover the emitter, the execution engine, failure injection and fuzz
classification, so **a green offline run on its own does not mean the pipeline works**:

```bash
docker compose up -d n8n
eval "$(python scripts/bootstrap_n8n.py --base-url http://localhost:5678)"
WORKFLOWGUARD_TEST_N8N_BASE_URL=http://localhost:5678 \
WORKFLOWGUARD_TEST_N8N_API_KEY="$N8N_API_KEY" \
  pytest packages/workflow-core/tests apps/api/tests -m integration
```

The mock endpoints are served by the test session itself, so no running API is needed: the
engine and the mock server have to share one registry object.

## CLI

Install the core package locally, then use the `workflowguard` command in CI or local scripts.
`test`, `fuzz`, `check` and `report` execute the workflow and need `WORKFLOWGUARD_N8N_BASE_URL`
and `WORKFLOWGUARD_N8N_API_KEY`; `validate`, `evaluate`, `cost` and `compare` execute nothing and
need no engine. The CLI serves its own mock endpoints for the duration of a run, so integration
calls never leave the machine.

```bash
pip install -e packages/workflow-core
workflowguard validate examples/json/valid-workflow.json
workflowguard evaluate examples/json/valid-workflow.json --prompt "Approve requests, then notify Slack."
workflowguard test examples/json/valid-workflow.json --json
workflowguard cost examples/json/valid-workflow.json --executions-day 500 --json
workflowguard check examples/demo/broken-ai-invoice-workflow.json --prompt "$(cat examples/demo/invoice-requirement.md)" --json
workflowguard report examples/demo/broken-ai-invoice-workflow.json --format markdown
workflowguard compare examples/json/valid-workflow.json examples/json/orphan-node.json --json
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

AI requirement responses are validated against the `RequirementSpec` schema before use. AI-generated tests are validated against the `TestGenerationResult`/`WorkflowTest` schemas before storage. AI repair patches are validated against the `RepairPatch` schema and only applied to a temporary candidate for preview. Provider errors, timeouts, malformed output, rate limits, and missing credentials fall back to deterministic generation.

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

Tests execute for real. The canonical workflow is compiled into an n8n workflow, published,
triggered per test, and the execution is read back and translated into canonical node and edge
ids -- so assertions and coverage mean what they always did.

Two things are deliberately withheld. **An integration call never reaches its declared
destination**: every external API, database, email and LLM node is redirected to WorkflowGuard's
own mock endpoints, which serve the test's mocked integrations and turn its failure injections
into genuine 429s, 500s, timeouts and malformed responses. **Uploaded Python and BPMN scripts are
not executed.** Uploaded *JavaScript* is, in a contained runner, because a branch downstream of a
code node that never ran takes an arbitrary path and the run then reports a confident verdict
about something it never evaluated. See the Security Posture section of
[docs/architecture.md](docs/architecture.md).

Because failures are real rather than modelled, a node configured with retries genuinely retries:
a single injected timeout is survived and the run passes. To exhaust the retries, inject on each
attempt.

Test runs store execution order, branch decisions, external calls, retries, failures, duration,
token estimates, assertion results, coverage, and any warnings about parts of the run that were
approximated rather than measured.

Coverage is workflow coverage, not source-code coverage:

- Node Coverage
- Edge Coverage
- Branch Coverage
- Requirement Coverage
- Overall Test Coverage

## Cost Intelligence

WorkflowGuard estimates:

- Cost per execution
- Daily, monthly, and annual projections
- LLM/model token costs
- External API, compute, database, storage, email/messaging, and configurable node costs
- Scenario forecasts using executions/day, monthly executions, average payload size, token estimates, and failure/retry rate

Pricing is stored in an editable/versioned catalog with provider, model, effective date, unit costs, currency, source, and metadata. Seeded pricing is a development assumption, not a billing authority.

Cost estimates differ from actual provider bills because real invoices can include exact tokenizer behavior, free tiers, tiered rates, discounts, taxes, regional pricing, minimum charges, cache discounts, batch discounts, retries outside the workflow, and provider-side rounding. Every estimate response includes the assumptions used.

Optimization findings are deterministic unless explicitly marked otherwise. WorkflowGuard may recommend benchmarking cheaper models or caching repeated calls, but it does not claim two models are equivalent without evidence.

## Repair

Repair proposals are safe patches against the canonical workflow. The lifecycle is:

Finding -> patch proposal -> schema validation -> temporary candidate -> validation -> semantic evaluation -> generated test run -> cost estimate -> before/after preview -> accept or reject.

Accepted repairs create a new workflow version and preserve the original workflow, files, tests, and history. Safety flags call out new external destinations, removed approval nodes, removed workflow nodes, and other behavior changes detected by static comparison.

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
- `GET /api/pricing`
- `POST /api/pricing`
- `GET /api/workflows/{id}/cost`
- `POST /api/workflows/{id}/cost`
- `GET /api/workflows/{id}/versions/compare`
- `POST /api/workflows/{id}/repairs/generate`
- `GET /api/workflows/{id}/repairs`
- `POST /api/repairs/{proposal_id}/accept`
- `POST /api/repairs/{proposal_id}/reject`
- `POST /api/workflows/{id}/quality-gate`
- `GET /api/workflows/{id}/quality-gate`
- `GET /api/workflows/{id}/history`
- `GET /api/workflows/{id}/report?format=json|markdown|html`
- `GET /api/dashboard`
- `GET /api/ready`
- `GET /api/metrics`

## Quality Gates and CI/CD

Quality gates combine stored structural, prompt-alignment, security, reliability, maintainability, test coverage, critical test, critical security, and optional cost-increase signals. The default thresholds are intentionally strict for CI:

- Structural score >= 90
- Prompt alignment >= 90
- Security >= 85
- Reliability >= 80
- Maintainability >= 70
- Test coverage >= 85
- No high/critical failed tests
- No critical security findings
- Monthly cost increase <= 20% when a before/after baseline is supplied

The `workflowguard check` CLI command exits `0` on pass, `1` on gate failure, and `2` when parsing fails. `.github/workflows/workflowguard.yml` shows a PR workflow that detects changed workflow files, runs deterministic checks, and uploads JSON/Markdown reports. It does not require paid AI calls by default; AI-assisted extraction can be enabled through CI secrets.

## Reports and Audit History

Workflow reports are exportable as JSON, Markdown, or HTML. Reports include workflow/version metadata, original requirement, overall and dimension scores, validation findings, prompt alignment evidence, security/reliability findings, test results, coverage, cost estimates, optimization opportunities, and quality gate results.

Audit events are persisted for upload, validation, evaluation, test generation, test execution, cost estimation, repair proposal/accept/reject, and quality gate checks. They are visible in Workflow Detail > History and available through the history API.

## Demo

The invoice demo lives under `examples/demo`:

- `invoice-requirement.md`
- `broken-ai-invoice-workflow.json`
- `correct-invoice-workflow.json`
- `cost-scenario.json`
- `expected-findings.md`
- `repair-example.json`

Upload `broken-ai-invoice-workflow.json` as AI-generated and paste the requirement. WorkflowGuard should flag that the high-value invoice path bypasses manual approval before SAP, generate tests for the missing branch behavior, estimate cost, fail quality gates, and produce repair/cost/report artifacts.

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
- `WORKFLOWGUARD_N8N_BASE_URL`
- `WORKFLOWGUARD_N8N_API_KEY` (needs the `workflow:activate` scope)
- `WORKFLOWGUARD_N8N_RUN_TIMEOUT_SECONDS`
- `WORKFLOWGUARD_MOCK_BASE_URL` (must be reachable **from n8n**)
- `WORKFLOWGUARD_TEST_N8N_BASE_URL` / `WORKFLOWGUARD_TEST_N8N_API_KEY` (integration tests only)

## Current Limitations

- Tests execute in n8n and cannot reach real services: every integration call is redirected to
  WorkflowGuard's own mock endpoints, so an emitted workflow carries no credentials and a passing
  test says nothing about whether real credentials work.
- Uploaded JavaScript is executed, in an external task runner on a network with no route off the
  host, under a task timeout and resource limits. Uploaded Python and BPMN scripts are not
  executed, and the run says so.
- Running a test requires a reachable n8n. There is no in-process fallback: reporting invented
  coverage to a pipeline would be worse than failing loudly.
- BPMN executes as a control-flow skeleton. The BPMN parser records an element's type but
  extracts no parameters, so gateways and branching are genuinely exercised while the work at
  each node is mocked.
- Generated tests are reviewable starting points, not trusted truth.
- Cost estimates are planning estimates, not provider bills.
- Repair patches operate on canonical workflow versions; original uploaded source files are preserved but not rewritten.
- Semantic evaluation is static and best-effort; it does not prove runtime correctness.
- The deterministic requirement extractor is intentionally conservative and can miss nuanced requirements without an AI provider.
- Observability is limited to structured request logs, request IDs, health/readiness, and basic Prometheus-style metrics; it does not ingest live workflow runtime telemetry yet.
- BPMN diagram rendering is not enabled in the UI yet, but BPMN metadata is preserved for adding `bpmn-js`.
- Authentication and multi-user project isolation are intentionally deferred.

## Roadmap

Valuable next steps include authentication and project-level authorization, background job workers for long evaluations, deeper native BPMN rendering, richer workflow-engine adapters, live execution telemetry ingestion, configurable organization-level quality policies, and provider-backed repair benchmarking.
