# Deploying to Vercel + Supabase

The primary hosted deployment: the Next.js frontend and the FastAPI backend both
run on Vercel, with Postgres on Supabase. Deploys are driven by
`.github/workflows/deploy.yml`, not by Vercel's own Git integration.

For the container-based alternative see the Render section of
[deployment.md](deployment.md).

## Topology

Two Vercel projects from this one repository:

| | `workflowguard-api` | `workflowguard-web` |
| --- | --- | --- |
| Root Directory | *(repo root, leave blank)* | `apps/web` |
| Framework Preset | **FastAPI** | **Next.js** |
| Build / Install Command | *(defaults)* | *(defaults)* |
| Runtime | Python 3.12 (`.python-version`) | Node 22 |

The API is a single Vercel Function. Vercel's FastAPI preset resolves the
entrypoint from the top-level `app` in `index.py` at the repo root, then routes
every path to it — which is why the root `vercel.json` has no `rewrites`, only a
`functions` entry keyed on `index.py`.

**Set the API project's framework preset to FastAPI explicitly.** The repo root
also contains a `package.json`, and although it declares no dependencies (so
Next.js detection should not fire), it is worth not relying on that. Confirm the
first build log shows a Python install rather than `npm install`.

### Why the frontend has no CORS configuration

`apps/web/vercel.json` rewrites `/api/:path*` to the API project's domain, and
the web project sets `NEXT_PUBLIC_API_BASE_URL=/api` — a relative path. So:

- Browser calls are **same-origin**. No preflight, no CORS, ever, from our own
  frontend — including from preview deployments, whose URLs are unique per
  deployment and could never be added to a static allowlist in advance.
- The value baked into the JS bundle at build time is the constant `/api`, so
  the web build never needs to know the API's domain. Without this, the web
  build would depend on a URL that only exists after the API deploys.

The cost is one extra CDN hop on browser traffic. Server-side rendering does not
go through the rewrite — it needs an absolute URL, which is why the web project
also sets `INTERNAL_API_BASE_URL`. `apps/web/src/lib/api.ts` already prefers
that variable, so no application code changes for this.

`CORS_ORIGINS` on the API therefore matters only for **third parties** calling
the API directly from a browser.

## Supabase

Create the project in the same region the API deploys to (`iad1` by default, set
in `vercel.json`) — every request makes at least one database round trip.

Two different connection strings, for two different consumers:

| Consumer | Which string | Port |
| --- | --- | --- |
| API runtime (Vercel env) | **Transaction** pooler | `6543` |
| Migrations (GitHub Actions) | **Session** pooler | `5432` |

Both use the `aws-N-<region>.pooler.supabase.com` host and the
`postgres.<project-ref>` username.

Two traps worth stating plainly:

- **Do not use the direct `db.<ref>.supabase.co:5432` connection for
  migrations.** It is IPv6-only unless you buy the IPv4 add-on, and
  GitHub-hosted runners have no IPv6. The failure looks like a connection
  timeout, which reads as a firewall problem rather than an addressing one.
- **Migrations need session mode, not transaction mode.** Transaction mode hands
  each transaction a different backend, which DDL and Alembic's locking do not
  tolerate.

Rewrite both to the `postgresql+psycopg://` scheme, and strip any
`?pgbouncer=true` that Supabase's UI appends — `Settings.sqlalchemy_database_url`
preserves the query string and libpq rejects the unknown keyword.

`db/session.py` disables psycopg's server-side prepared statements
(`prepare_threshold=None`) because the transaction pooler cannot support them;
leaving them on produces intermittent `DuplicatePreparedStatement` errors rather
than a clean failure.

## Environment variables

Set on the **`workflowguard-api`** Vercel project:

```bash
WORKFLOWGUARD_ENVIRONMENT=production
WORKFLOWGUARD_DATABASE_URL=postgresql+psycopg://postgres.<ref>:<pw>@aws-N-<region>.pooler.supabase.com:6543/postgres
WORKFLOWGUARD_CORS_ORIGINS=["https://workflowguard.vercel.app"]
WORKFLOWGUARD_AI_PROVIDER=none
WORKFLOWGUARD_MAX_UPLOAD_BYTES=4000000
```

Set on the **`workflowguard-web`** Vercel project:

```bash
NEXT_PUBLIC_API_BASE_URL=/api
INTERNAL_API_BASE_URL=https://workflowguard-api.vercel.app/api
```

`MAX_UPLOAD_BYTES` must stay below the platform's 4.5 MB body cap (see Limits).

## GitHub secrets

| Secret | Value |
| --- | --- |
| `VERCEL_TOKEN` | Vercel account token (Account Settings → Tokens) |
| `VERCEL_ORG_ID` | from `.vercel/project.json` after a local `vercel link` |
| `VERCEL_PROJECT_ID_API` | ditto, for `workflowguard-api` |
| `VERCEL_PROJECT_ID_WEB` | ditto, for `workflowguard-web` |
| `SUPABASE_MIGRATION_URL` | the **session** pooler URL, `postgresql+psycopg://…:5432/postgres` |

The runtime database URL is deliberately **not** a GitHub secret — it is a Vercel
project variable, so it is injected into the function and never passes through CI.

**Turn off Vercel's Git integration auto-deploy on both projects** (Settings →
Git → Ignored Build Step, or disconnect Git). Otherwise Vercel deploys on push in
parallel with the migrate job and the ordering guarantee below is lost.

## Pipeline

```
test        (reuses .github/workflows/ci.yml)
  └─ migrate      alembic upgrade head   [main only]
       └─ deploy-api      + /api/health and /api/ready smoke test
            └─ deploy-web
```

Pull requests run `test` and a **web preview** only — no migration, no API
deploy. Because the preview's `/api/*` rewrite points at production, a preview is
a fully working app against production data. There is no preview database.

Migrations run before the deploy, so the schema is briefly **ahead** of the
running code. Every migration in `apps/api/alembic/versions/` is additive, which
makes that ordering correct.

> **Rule:** a migration must be backward-compatible with the previous release.
> Destructive changes need the two-deploy expand/contract sequence — first deploy
> code that tolerates both shapes, then remove the old shape.

If the migrate job fails, `deploy-api` and `deploy-web` are skipped and the live
deployment keeps serving the previous code against the previous schema.

## Limits

These are platform limits, not configuration choices:

- **4.5 MB** maximum request *and* response body. Exceeding it returns
  `413 FUNCTION_PAYLOAD_TOO_LARGE` from Vercel before your code runs — which is
  why `upload_workflow` checks the size itself and returns a 413 that says what
  the limit is.
- **300s** maximum function duration on Hobby (default and maximum).
- **500 MB** uncompressed Python bundle. `vercel.json` uses `excludeFiles` to
  keep tests, docs, examples and the web app out of it — Python bundles
  everything reachable by default and has no tree-shaking.
- **Cold starts** of a few seconds: importing lxml, networkx, sqlalchemy and
  psycopg, plus building the engine at module scope, then a first pooler
  connection.

### No background jobs

Every endpoint is synchronous. `POST /workflows/{id}/tests/run` and
`POST /workflows/{id}/fuzz` block the request for as long as they take. They fit
inside 300s for realistic workflows, and keeping `WORKFLOWGUARD_AI_PROVIDER=none`
keeps the evaluation endpoints deterministic and fast.

With an AI provider configured, `/evaluate`, `/tests/generate`, `/fuzz` and
`/repairs/generate` can each take 40s+ (a 20s provider timeout plus up to 20s of
rate-limit retry). Still inside the ceiling, but the synchronous design is not a
long-term answer — moving long runs to a queue is tracked as follow-up work.

## Security posture

Stated plainly, because it is a deliberate choice and not an oversight:

- **The API is deployed unauthenticated.** There are no API keys, tokens, or
  per-caller scoping. Anyone who knows the URL can create, read, modify, delete
  and run analyses on any workflow.
- **There is no rate limiting or quota.**
- **There is no tenant isolation.** All workflows are globally visible.
- `/docs`, `/redoc` and `/api/openapi.json` are public.
- `WORKFLOWGUARD_AI_PROVIDER=none` is what keeps this safe to expose: the AI
  endpoints fall back to deterministic logic, so anonymous traffic cannot
  generate provider spend. **Do not enable an AI provider until authentication
  exists.**

Authentication and project-level authorization are tracked as follow-up work.

## Rolling back

Vercel keeps every deployment. Promote a previous one from the project's
Deployments tab (⋯ → Promote to Production) — this reverts code only. If the bad
release included a migration, roll that back separately with
`alembic downgrade <revision>` against the session pooler, and only if the
migration was reversible.

## First-time setup order

Do steps 3 and 4 by hand before wiring up CI — debugging a Python bundle through
GitHub Actions logs is far slower than through a local `vercel deploy`.

1. Create the Supabase project; collect both connection strings.
2. Run `alembic upgrade head` from your machine against the session pooler to
   prove the schema applies.
3. `vercel link` at the repo root → API project. Set the FastAPI preset and the
   API env vars. `vercel deploy --prod`. Check `/api/health` and `/api/ready`
   (`/ready` is the one that proves the database connection works).
4. `vercel link` in `apps/web` → web project. Set its two env vars. Deploy.
   Confirm in devtools that the browser calls `/api/*` on its own origin.
5. Disable Git auto-deploy on both projects.
6. Add the five GitHub secrets. Push to `main` and watch the job ordering hold.
