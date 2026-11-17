# TaskFlow — Multi-Tenant SaaS Project Management

A Jira-style product where every company gets its own isolated workspace with Kanban boards, sprints, custom workflows, an audit log, webhooks and subscription billing.

**Stack:** Django 5 + Django REST Framework · PostgreSQL (SQLite locally) · React + TypeScript + Vite · Celery + Redis · Stripe Billing (with a built-in mock mode) · Docker · GitHub Actions

| | |
|---|---|
| Live demo | _add your Vercel URL here after deploying (see [docs/DEPLOY.md](docs/DEPLOY.md))_ |
| API docs | `/api/docs/` (Swagger) · `/api/redoc/` |
| Architecture | [docs/architecture.md](docs/architecture.md) |
| Test results | [docs/test-results.md](docs/test-results.md) |

## Features

**Multi-tenancy & access**
- Shared-schema tenancy: every tenant row carries a `workspace` FK, scoped in three layers (model base class, a DRF mixin that resolves the workspace from the URL and checks membership, and automated cross-tenant leak tests).
- One user can belong to many workspaces with a different role in each (Owner / Admin / Member / Viewer). Invitations by email token.
- Another tenant's workspace is indistinguishable from a non-existent one (always 404).

**Work management**
- Projects with auto-numbered issues (`WEB-12`), types (task / bug / story / epic), priorities, labels, story points, due dates, parent/child.
- **Drag-and-drop Kanban** (dnd-kit): optimistic UI, fractional ranking so a move writes one row, WIP limits, keyboard accessible.
- **Custom workflows**: editable statuses and allowed transitions per project, enforced on the server *and* greyed out in the UI.
- Sprints and backlog: plan, start, close (carry-over or back to backlog), burndown and velocity charts.
- Comments with `@mentions`, file attachments (type/size checked, served only through a membership-checked endpoint).
- Global search / command palette (`Ctrl K`), board filters, keyboard shortcuts (`c` create, `/` search), dark mode, CSV import/export (Project → Workflow settings). Saved filters exist in the API (`/saved-filters/`) but have no UI yet.

**Platform**
- **Audit log**: every create/update/delete recorded automatically with actor and field-level before/after.
- **Webhooks**: HMAC-SHA256 signed, retried with exponential backoff, delivery log with redeliver, SSRF protection.
- **Celery jobs**: notification and invitation emails, weekly workspace report (Celery Beat), webhook retry sweep.
- **Billing**: Free / Pro / Business plans with enforced limits (members, projects, storage, webhooks) returned as structured `402` responses that drive an upgrade prompt. Stripe Checkout, Customer Portal and idempotent signature-verified webhooks, plus a **mock provider** so everything works with no Stripe account.
- In-app notifications, dashboard (status mix, created-vs-resolved flow, velocity, workload), weekly report.

## Run it locally (no Docker needed)

Requires Python 3.12+ and Node 20+.

```bash
# 1. Backend  (http://localhost:8000)
cd backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py seed_demo                                # two demo companies with realistic data
python manage.py runserver

# 2. Frontend  (http://localhost:5173) — in a second terminal
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and use the demo buttons on the login page (password `demo12345`):

| Account | Workspace | Role |
|---|---|---|
| `alice@acme.test` | Acme Robotics (Pro) | Owner — and a **Viewer** in Globex |
| `bob@acme.test` | Acme Robotics | Admin |
| `carol@acme.test`, `dave@acme.test` | Acme Robotics | Member |
| `erin@acme.test` | Acme Robotics | Viewer |
| `gina@globex.test` | Globex Labs (Free) | Owner |

Locally, Celery runs inline (no Redis needed) and billing uses the mock checkout.

## Run the full stack with Docker

```bash
docker compose up --build            # web http://localhost:8080 · API docs /api/docs/
docker compose exec api python manage.py seed_demo
```
Starts PostgreSQL, Redis, the API (gunicorn), a Celery worker, Celery Beat and the nginx-served frontend. Copy `.env.example` to `.env` to customise (optional).

## Tests

```bash
cd backend && pytest --cov=apps          # 98 tests, 97 run on SQLite + 1 PostgreSQL-only concurrency test
cd frontend && npm test && npx tsc -b && npm run build
cd loadtest && locust -f locustfile.py --host http://localhost:8000 --headless -u 30 -r 5 -t 60s
```
Browser smoke tests (Playwright) live in [`e2e/`](e2e). Results: [docs/test-results.md](docs/test-results.md).

## Using real Stripe (test mode)

Leave `STRIPE_SECRET_KEY` empty and billing runs in mock mode. To use real Stripe, create a free test-mode account, then set `STRIPE_SECRET_KEY`, `STRIPE_PRICE_PRO`, `STRIPE_PRICE_BUSINESS` and `STRIPE_WEBHOOK_SECRET` (forward events locally with `stripe listen --forward-to localhost:8000/api/billing/stripe-webhook/`). No code changes are needed. Full walkthrough: [docs/STRIPE.md](docs/STRIPE.md); `backend/scripts/stripe_setup.py` creates the prices for you. After checkout the app also calls `POST /billing/sync/`, so upgrades don't depend on the webhook arriving.

## Project layout

```
backend/    Django project — apps: accounts, workspaces (tenancy), projects, audit, webhooks, billing, notifications
frontend/   React app (pages/, components/, api/)
loadtest/   Locust workload + results
e2e/        Playwright smoke scripts
docs/       architecture, deployment, test results, presentation outline
.github/    ci.yml (test + build + docker smoke) · deploy.yml (images + Render deploy)
```

## Known limitations

- Real Stripe has not been exercised end-to-end (it needs your Stripe account). The provider, sync and signed-webhook code are tested against a fake Stripe client and real HMAC signatures, and the mock provider covers the full user flow. Follow docs/STRIPE.md to verify with test keys.
- The Docker images are built and smoke-tested by CI; they were not built on the author's machine.
- No AI features yet (planned as an optional, flag-gated `ai` app).
