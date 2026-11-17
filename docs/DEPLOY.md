# Deploying TaskFlow (beginner-friendly)

You already know how to host a static site on Vercel. This is the same idea plus one backend service.

```
Browser ──► Vercel (React frontend) ──► Render (Django API + PostgreSQL)
```

Total cost for a demo: **$0** on free tiers. Free-tier terms change, so check the current limits on each pricing page. As of writing, free Render web services sleep after inactivity (first request takes ~30-60 s to wake) and free Render Postgres databases are time-limited, so **create them a few days before your presentation, not weeks**.

## Before you start
1. Put the project on GitHub (a new empty repo, then push this folder).
2. Make a free account on [render.com](https://render.com) and [vercel.com](https://vercel.com), both signed in with GitHub.

## Step 1 — Backend on Render
1. Render dashboard → **New → Blueprint** → choose your repo. Render reads `render.yaml` and creates the API and the database.
2. When asked for the values marked `sync: false`, leave the Stripe ones empty (mock billing) and put a placeholder (e.g. `https://example.com`) for `FRONTEND_URL`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`. You fix these in Step 3.
3. Wait for the first deploy to go green. Open `https://<your-api>.onrender.com/health/`. You should see `{"status": "ok"}`. Also try `/api/docs/`.
4. The demo companies load automatically on boot (`SEED_DEMO=1`).

## Step 2 — Frontend on Vercel
1. **Add New → Project** → import the same repo.
2. Set **Root Directory** to `frontend`. Framework is detected as Vite.
3. Add an environment variable: `VITE_API_URL` = your Render URL (no trailing slash), e.g. `https://taskflow-api.onrender.com`.
4. Deploy. `frontend/vercel.json` makes deep links like `/w/acme-robotics/...` work on refresh.

## Step 3 — Connect them (CORS)
Back in Render → your service → **Environment**, set all three to your Vercel URL (no trailing slash), then redeploy:
- `FRONTEND_URL` = `https://<your-app>.vercel.app`
- `CORS_ALLOWED_ORIGINS` = `https://<your-app>.vercel.app`
- `CSRF_TRUSTED_ORIGINS` = `https://<your-app>.vercel.app`

Open the Vercel URL and sign in with `alice@acme.test` / `demo12345`.

## Step 4 — CI/CD (GitHub Actions)
- `ci.yml` runs automatically on every push and PR: migrations check, 86 tests against PostgreSQL, TypeScript build, Docker image builds, and a full-stack smoke test.
- `deploy.yml` runs after CI succeeds on `main`. It publishes container images to GitHub Container Registry and can trigger Render:
  - Render service → **Settings → Deploy Hook** → copy the URL → GitHub repo → **Settings → Secrets → Actions** → add `RENDER_DEPLOY_HOOK_URL`.
  - Optionally add a repository variable `API_URL` (your Render URL) so the workflow waits for `/health/`.
- Vercel redeploys the frontend by itself on each push.

## Turning on real Stripe (optional, test mode)
1. Create a free Stripe account and stay in **Test mode**.
2. Products → create "Pro" ($12/mo) and "Business" ($49/mo) recurring prices → copy each `price_...` ID.
3. Developers → API keys → copy the secret key (`sk_test_...`).
4. Developers → Webhooks → add endpoint `https://<your-api>.onrender.com/api/billing/stripe-webhook/` with events `checkout.session.completed`, `customer.subscription.created/updated/deleted`, `invoice.payment_failed` → copy the signing secret (`whsec_...`).
5. Set `STRIPE_SECRET_KEY`, `STRIPE_PRICE_PRO`, `STRIPE_PRICE_BUSINESS`, `STRIPE_WEBHOOK_SECRET` on Render and redeploy. Pay with test card `4242 4242 4242 4242`.

## After the demo
Set `SEED_DEMO=0`, since the demo accounts share a public password. Free tier limits mean the API's first request after idle will be slow, so open the site a minute before presenting.

## Troubleshooting
| Symptom | Likely cause |
|---|---|
| Login says "Network error" / CORS error in the browser console | Step 3 values missing or have a trailing slash / wrong URL |
| Refreshing a page gives 404 on Vercel | `vercel.json` not in the `frontend` root directory |
| API returns 400 "Invalid host header" | add your domain to `ALLOWED_HOSTS` (default `.onrender.com`) |
| First request takes a minute | free-tier cold start |
