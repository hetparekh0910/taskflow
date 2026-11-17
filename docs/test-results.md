# Test results

All numbers below were produced on 14 Nov 2026 against the current code, on the development machine (SQLite, Django dev server) unless stated otherwise.

## Backend automated tests (pytest)

**86 tests: 85 pass, 1 skipped** (the concurrency test needs PostgreSQL row locking and runs in CI). **Line coverage 86%** (CI gate: 85%).

| Suite | Tests | What it proves |
|---|--:|---|
| `test_tenant_isolation.py` | 14 | A user in workspace A can never read, write or delete B's data via any endpoint, URL ID, body ID, attachment download, search or dashboard; foreign workspaces return the same 404 as missing ones |
| `test_permissions.py` | 14 | Viewer < Member < Admin < Owner matrix; last-owner protection; invitation flow; auth |
| `test_issues_workflow.py` | 18 | Numbering, validation, filters, custom workflows enforced, drag-and-drop ranking (one row written, rebalance, WIP limits), comments and mentions |
| `test_sprints_audit.py` | 12 | Sprint lifecycle and carry-over, burndown series, dashboard numbers, audit diffs and actors |
| `test_webhooks_notifications.py` | 16 | HMAC signature, retries with backoff, give-up, SSRF guard, rollback safety, notifications, weekly report email |
| `test_billing.py` | 11 | Plan limits (402 payloads), mock checkout upgrade/cancel, Stripe webhook idempotency and signature handling |
| `test_concurrency.py` | 1 | 8 threads x 6 creates yield gap-free unique issue keys (PostgreSQL, in CI) |

## Browser tests (Playwright, real Chromium against the running stack)
- Sign in → open board → **drag a card across columns → move persists after reload** (WEB-18: To Do 7→6, In Progress 1→2), no console errors.
- All 10 workspace pages load with **0 failed API requests and 0 console errors**.
- Mock billing: Free workspace upgrades via the simulated checkout and the plan badge updates.
- CSV: exported 131 issues, re-imported 131, count 131 → 262.

Scripts: [`e2e/`](../e2e). Frontend `tsc -b` and production build are clean.

## Load test (Locust: 30 users, ramp 5/s, 60 s; ~80% reads / 20% writes)

Dev server on SQLite in a sandbox, so treat as a baseline. Production gunicorn + PostgreSQL will differ.

| Endpoint | Requests | Failures | Median | p95 | p99 |
|---|--:|--:|--:|--:|--:|
| GET board | 705 | 0 | 56 ms | 300 ms | 420 ms |
| GET issues (filtered) | 364 | 0 | 48 ms | 260 ms | 340 ms |
| GET dashboard | 195 | 0 | 24 ms | 220 ms | 330 ms |
| POST issue | 105 | 0 | 230 ms | 410 ms | 700 ms |
| POST move (drag) | 157 | 0 | 240 ms | 450 ms | 680 ms |
| POST comment | 89 | 0 | 31 ms | 250 ms | 460 ms |
| **All** | **1,675** | **0** | **61 ms** | **350 ms** | **450 ms** (≈28 req/s) |

Raw data: `loadtest/results_stats.csv`.

**A finding worth presenting.** The first run of this test produced 13 HTTP 500s (0.8%, all writes) with `database is locked`: SQLite allows one writer and concurrent requests collided. Fix: WAL journal mode, immediate write transactions and a 20 s busy timeout for SQLite (PostgreSQL, used in production, is unaffected). Re-run: 0 failures.

## Not yet verified
- Docker images and `docker compose` stack: syntax validated, **not built locally**; the CI `docker` job builds and smoke-tests them on first push.
- Real Stripe: needs a Stripe account (mock provider and synthetic signed-event tests only).
- The deployed Vercel/Render environment.


## Update: Stripe + frontend tests
- Backend: **98 tests (97 pass, 1 PostgreSQL-only skipped on SQLite), 87% coverage**. New `test_stripe_provider.py` covers checkout/portal/sync/error-wrapping against a fake Stripe client, a real HMAC-signed webhook (this caught a bug with stripe-python 17 event parsing, now fixed), and the price setup script.
- Frontend: **47 Vitest tests** (board move planning, API client token refresh, types, UI components, auth pages).
