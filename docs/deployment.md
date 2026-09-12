# Deployment

WorkflowGuard needs three hosted resources:

- A Next.js frontend
- A FastAPI backend
- A PostgreSQL database for workflows, versions, files, validation runs, evaluations, tests, cost estimates, repairs, and audit history

## Hosting Options

- **[Vercel + Neon](vercel.md)** -- the primary hosted deployment, deployed
  automatically from `main` by `.github/workflows/deploy.yml`. Both apps run as
  Vercel projects; Postgres is managed by Neon.
- **Render** (below) -- the container-based alternative. It is the only path that
  exercises `docker/api.Dockerfile`, and it has no function duration or request
  body limits to work around.

## Alternative: Render

The included `render.yaml` defines all three pieces for Render:

- `workflowguard-web`: Next.js frontend
- `workflowguard-api`: Dockerized FastAPI backend
- `workflowguard-db`: managed PostgreSQL

Render Blueprints are defined in a root `render.yaml`. Docker services can point at Dockerfiles with `dockerfilePath` and `dockerContext`, and environment variables can reference managed Postgres using `fromDatabase`.

## Deploy On Render

1. Push this repository to GitHub.
2. In Render, create a new Blueprint from the repository.
3. Keep the default service names, or update these variables if you rename them:
   - API `WORKFLOWGUARD_CORS_ORIGINS`
   - Web `NEXT_PUBLIC_API_BASE_URL`
4. Deploy the Blueprint.
5. Open the API health endpoint:
   - `https://workflowguard-api.onrender.com/api/health`
6. Open the frontend:
   - `https://workflowguard-web.onrender.com`

The API container runs `alembic upgrade head` before starting Uvicorn, so database tables are created automatically on deploy. This is Render-specific: the Vercel deployment has no container start, so it runs migrations as a CI job instead (see [vercel.md](vercel.md)).

## Where Workflow Data Is Stored

Uploaded workflows and all analysis history are stored in PostgreSQL:

- `workflows`
- `workflow_versions`
- `workflow_files`
- `workflow_nodes`
- `workflow_edges`
- `validation_runs`
- `validation_findings`
- `requirement_specifications`
- `evaluation_runs`
- `workflow_tests`
- `workflow_test_runs`
- `cost_estimates`
- `repair_proposals`
- `audit_events`
- `workflow_attachments`

The frontend stores no durable workflow data. If the frontend is redeployed, data remains in PostgreSQL. If the database is deleted, the workflow history is deleted.

## Environment Variables

Backend:

```bash
WORKFLOWGUARD_ENVIRONMENT=production
WORKFLOWGUARD_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/workflowguard
WORKFLOWGUARD_CORS_ORIGINS=["https://YOUR_FRONTEND_DOMAIN"]
WORKFLOWGUARD_AI_PROVIDER=none
WORKFLOWGUARD_AI_API_KEY=
WORKFLOWGUARD_AI_MODEL=gpt-4o-mini
WORKFLOWGUARD_AI_TIMEOUT_SECONDS=20
```

Frontend:

```bash
NEXT_PUBLIC_API_BASE_URL=https://YOUR_API_DOMAIN/api
INTERNAL_API_BASE_URL=https://YOUR_API_DOMAIN/api
```

Do not set `NODE_ENV=production` manually on Render for the frontend. Render applies environment variables during build; forcing `NODE_ENV=production` can cause npm to omit build-time packages before `next build` runs.

For Render, `INTERNAL_API_HOST` and `INTERNAL_API_PORT` are used instead of `INTERNAL_API_BASE_URL` so server-rendered pages can call the API over Render's private network.

## Production Notes

- Use a paid Postgres plan for real data. Free database tiers are fine for demos but are not a backup strategy.
- Add database backups before trusting the platform with important workflow history.
- Keep `WORKFLOWGUARD_AI_PROVIDER=none` unless you intentionally enable AI features.
- Store AI API keys only as provider secrets, never in the repo.
- Update CORS when you add a custom frontend domain.

## n8n, and the four secrets the blueprint cannot set

`render.yaml` creates four services: the API, the web app, **n8n** (the engine workflow tests
actually execute in) and **its task runner** (where uploaded JavaScript runs, in a separate
process so a snippet that hangs or allocates takes the runner down rather than the engine every
other test is running in). n8n gets its own Postgres, because two products sharing one schema is
a migration conflict waiting to happen and n8n's execution tables churn hard.

Several values are marked `sync: false`, because Render's blueprint cannot produce them. Set
them before the first deploy.

**Secrets:**

| Variable | On | What it is |
| --- | --- | --- |
| `N8N_ENCRYPTION_KEY` | n8n | Encrypts stored credentials. **Never regenerate it** - every stored credential becomes unreadable. |
| `N8N_RUNNERS_AUTH_TOKEN` | n8n *and* the runner | Any long random string, but it must be **the same value in both**, or the runner cannot register and every code node fails. |
| `WORKFLOWGUARD_N8N_API_KEY` | API | See below; it needs the `workflow:activate` scope. |
| `WORKFLOWGUARD_AI_API_KEY` | API | Optional, unrelated to execution. |

**Addresses the blueprint cannot know.** A Render internal hostname is the service name plus a
*generated suffix* - `workflowguard-n8n-a1b2`, not `workflowguard-n8n` - so none of these can be
written ahead of the first deploy. Take each from the relevant service's **Connect > Internal**
panel (a private service also shows it as its **Service Address**) and include the scheme:

| Variable | On | Set to |
| --- | --- | --- |
| `WORKFLOWGUARD_N8N_BASE_URL` | API | n8n's internal address, editor port: `http://workflowguard-n8n-a1b2:5678` |
| `WORKFLOWGUARD_MOCK_BASE_URL` | API | The **API's own** internal address plus `/mock`. Private traffic to a web service goes to **port 10000** whatever the process binds locally: `http://workflowguard-api-a1b2:10000/mock` |
| `N8N_RUNNERS_TASK_BROKER_URI` | runner | n8n's internal address on the broker port: `http://workflowguard-n8n-a1b2:5679` |
| `DB_POSTGRESDB_HOST` / `_PORT` | n8n | From the n8n database's internal connection details. `fromDatabase` exposes `connectionString`, `user`, `password` and `database` but **not** host or port, and n8n takes its connection in parts rather than as a URL. |

Getting `WORKFLOWGUARD_MOCK_BASE_URL` wrong is the failure worth knowing in advance: n8n reaches
nothing, every mocked integration call is refused, and runs fail for reasons that look like the
workflow's fault rather than the deployment's.

### Getting the API key

n8n is a **private service**: nothing outside the blueprint needs the editor, and an exposed n8n
is an exposed set of workflow credentials. That does mean the key cannot be created through a
browser as things stand. Either:

- port-forward to the service and run `python scripts/bootstrap_n8n.py --base-url
  http://localhost:5678`, which creates the owner and mints a scoped key without the UI; or
- temporarily change `type: pserv` to `type: web` for n8n, create the key in Settings > n8n API,
  then change it back.

Without the `workflow:activate` scope, publishing a run fails with a bare `403` that says
nothing about which scope is missing.

### What this costs, and what it does not buy

- **The free plan is not enough for the engine.** Free services spin down when idle, and a run
  in flight when n8n spins down fails for reasons unrelated to the workflow. n8n and its runner
  are on `starter` for that reason.
- **Test runs are not free of side effects on the wallet** either: every run publishes and
  deletes a workflow in n8n and stores an execution, which is why pruning is configured.
- **This does not make tests hit real services.** Every integration call is still redirected to
  the API's `/mock` endpoints, so a passing test says nothing about whether real credentials
  work. See `.claude/plans/live-endpoint-auth-checks.md` for what that would take.

### What has and has not been verified

Checked against Render's own documentation: `pserv` and `runtime: image` are valid, the
`image.url` shape is right, private services take `envVars` and a `plan`, and `fromDatabase`
exposes only `connectionString`, `connectionPoolString`, `user`, `password` and `database`. Two
errors were found and corrected that way - the n8n database block originally asked `fromDatabase`
for `host` and `port`, and the internal URLs were written without the generated suffix, so n8n
and the API would have been unable to find each other.

**Not verified:** the blueprint has never been applied to a live Render account. Run it through
Render's blueprint validator before relying on it, and expect the first deploy to need the
internal addresses filled in as described above - they do not exist until the services do.
