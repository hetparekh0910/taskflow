# 10-minute presentation outline

Aim: ~1 minute per slide, with a 3-minute live demo in the middle.

1. **Problem (1 min)**: Teams want Jira-like tracking but each company's data must be strictly separated, and the product needs billing. Who it's for; what "multi-tenant SaaS" demands (isolation, roles, plans).
2. **Solution at a glance (1 min)**: screenshot of the board + one-line feature list (boards, sprints, workflows, audit, webhooks, billing).
3. **Architecture (1.5 min)**: system diagram from `docs/architecture.md`. Say *why*: shared schema + `workspace_id` for simplicity, Celery for slow/unreliable work, Stripe behind a provider interface.
4. **Tenant isolation, the core design decision (1.5 min)**: the three layers; show the 14 cross-tenant leak tests. Mention 404-not-403.
5. **Live demo (3 min)**:
   - Sign in as Alice (Owner, Acme) → dashboard → drag a card on the board (workflow blocks an illegal move on the API project).
   - Open an issue: comment with an `@mention`, see the notification bell.
   - Switch workspace to Globex as Alice (**Viewer**: no write controls). Different data, same account.
   - Audit log shows the move with before/after. Webhooks page → test ping → signed delivery.
   - Billing as Gina (Globex, Free plan, already 3/3 members): invite a teammate on the Team page → 402 upgrade prompt → Billing → mock checkout to Pro → invite succeeds.
6. **Challenges and what I learned (1 min)**: ordering with fractional ranks; the `database is locked` load-test finding and fix; making webhooks safe (on-commit, HMAC, SSRF, retries); idempotent Stripe webhooks.
7. **Results (1 min)**: 86 tests, 86% coverage; 1,675-request load test with 0 failures, p95 350 ms; CI pipeline green.
8. **Next steps (0.5 min)**: real Stripe in test mode, AI features (issue drafting, sprint summaries, natural-language search), saved-filter UI, Postgres load test under gunicorn.

**Backup plan:** record the demo (3-5 min) in case the free-tier backend is cold or Wi-Fi fails.
