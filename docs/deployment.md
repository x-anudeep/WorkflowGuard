# Deployment

WorkflowGuard needs three hosted resources:

- A Next.js frontend
- A FastAPI backend
- A PostgreSQL database for workflows, versions, files, validation runs, evaluations, tests, cost estimates, repairs, and audit history

## Recommended Demo Hosting

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

The API container runs `alembic upgrade head` before starting Uvicorn, so database tables are created automatically on deploy.

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
