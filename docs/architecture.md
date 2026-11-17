# Architecture

## 1. System overview

```mermaid
flowchart LR
  U[Browser<br/>React SPA] -->|HTTPS + JWT| N[nginx / Vercel]
  N -->|/api/*| API[Django REST API<br/>gunicorn]
  API --> DB[(PostgreSQL)]
  API -->|enqueue| R[(Redis)]
  R --> W[Celery worker]
  B[Celery Beat] -->|weekly report<br/>webhook retry sweep| R
  W --> DB
  W -->|HMAC-signed POST| EXT[Customer webhook endpoints]
  W -->|SMTP| MAIL[Email]
  API <-->|Checkout / Portal| S[Stripe]
  S -->|signed webhooks| API
  API --> F[(Media volume<br/>attachments)]
```

Production topology used for the demo: **Vercel** (static frontend) → **Render** (API + Postgres). On Render's free tier there is no worker dyno, so Celery runs in eager mode (`CELERY_EAGER=1`); adding a worker and Redis is configuration only.

## 2. Tenant isolation (shared schema, `workspace_id` everywhere)

Every request to tenant data goes through `/api/w/{workspace_slug}/…`. Three independent layers:

```mermaid
sequenceDiagram
  participant C as Client (JWT)
  participant M as WorkspaceScopedMixin
  participant DB as PostgreSQL
  C->>M: GET /api/w/acme/issues/
  M->>M: authenticate (401 if anonymous)
  M->>DB: workspace by slug + Membership(user, workspace)
  alt no membership or no such workspace
    M-->>C: 404 (identical for both)
  else member
    M->>M: RolePermission: role >= required for action
    M->>DB: queryset.filter(workspace=ws)
    M-->>C: 200 only this tenant's rows
  end
```

1. **Model layer** – `TenantModel` gives every tenant table a non-null `workspace` FK.
2. **View layer** – `WorkspaceScopedMixin` resolves the workspace from the URL, verifies membership, filters every queryset, and sets the acting user for the audit log. `TenantPrimaryKeyRelatedField` / `WorkspaceMemberField` stop clients attaching another tenant's project, sprint, label, parent or assignee by guessing IDs.
3. **Test layer** – 14 cross-tenant tests (`tests/test_tenant_isolation.py`) attack every list endpoint, foreign IDs in URLs and request bodies, attachment downloads, search, dashboard and audit data.

## 3. Roles

| Capability | Viewer | Member | Admin | Owner |
|---|:-:|:-:|:-:|:-:|
| Read everything in the workspace | ✓ | ✓ | ✓ | ✓ |
| Create/edit issues, comment, attach, move on board | | ✓ | ✓ | ✓ |
| Delete issues; create projects, sprints, statuses/workflows | | | ✓ | ✓ |
| Invite/remove members, webhooks, audit log, start/close sprints | | | ✓ | ✓ |
| Billing, change ownership, delete workspace | | | | ✓ |

Roles are per workspace (a user can be Owner in one and Viewer in another).

## 4. Data model

```mermaid
erDiagram
  USER ||--o{ MEMBERSHIP : has
  WORKSPACE ||--o{ MEMBERSHIP : has
  WORKSPACE ||--o{ INVITATION : sends
  WORKSPACE ||--o{ PROJECT : owns
  PROJECT ||--o{ WORKFLOW_STATUS : defines
  PROJECT ||--o{ WORKFLOW_TRANSITION : allows
  PROJECT ||--o{ BOARD : has
  BOARD ||--o{ BOARD_COLUMN : has
  WORKFLOW_STATUS ||--o{ BOARD_COLUMN : shown_as
  PROJECT ||--o{ SPRINT : plans
  PROJECT ||--o{ ISSUE : contains
  WORKFLOW_STATUS ||--o{ ISSUE : status
  SPRINT ||--o{ ISSUE : includes
  ISSUE ||--o{ ISSUE : parent_of
  ISSUE }o--o{ LABEL : tagged
  ISSUE ||--o{ COMMENT : has
  ISSUE ||--o{ ATTACHMENT : has
  USER ||--o{ ISSUE : assigned
  WORKSPACE ||--o{ AUDIT_LOG : records
  WORKSPACE ||--o{ WEBHOOK : configures
  WEBHOOK ||--o{ WEBHOOK_DELIVERY : logs
  USER ||--o{ NOTIFICATION : receives
```

Key design choices:
- **Issue numbering**: `Project.issue_counter` incremented under `SELECT … FOR UPDATE` → gap-free `WEB-1, WEB-2…`. A threaded test (`test_concurrency.py`) proves uniqueness under contention; it runs in CI on PostgreSQL.
- **Drag-and-drop ordering**: `Issue.rank` is a float. Dropping between two cards sets the midpoint, so a move updates **one row**. If neighbours get closer than 1e-6 the column is rebalanced once. Tested.
- **Workflows**: with no transitions defined a project is *open* (any move allowed); once any exist, only listed moves are allowed. Enforced in the API for both PATCH and the board `move` action, and mirrored in the UI.
- **Audit log**: Django signals capture create/update/delete with a field-level diff and the acting user (a request-scoped `contextvar`). FKs are stored as readable values (`"status": {"old": "To Do", "new": "Done"}`).

## 4b. Request/event flows

**Webhook delivery**
```mermaid
sequenceDiagram
  participant V as View / signal
  participant E as emit()
  participant Q as Celery
  participant T as Target URL
  V->>E: emit(workspace, "issue.moved", data)
  E->>E: on_commit (never fires on rollback)
  E->>Q: deliver_webhook(delivery_id) per subscribed hook
  Q->>T: POST body + X-TaskFlow-Signature: sha256=HMAC(secret, ts.body)
  alt 2xx
    Q->>Q: mark delivered
  else error / non-2xx
    Q->>Q: attempts++, next_retry = 30s·2^n (cap 1h), give up after 5
  end
```

**Billing**
```mermaid
sequenceDiagram
  participant O as Owner
  participant API
  participant S as Stripe (or Mock)
  O->>API: POST /billing/checkout {plan}
  API->>S: create Checkout Session
  S-->>O: hosted payment page
  S->>API: webhook checkout.session.completed (signature verified)
  API->>API: StripeEvent insert (unique id) → idempotent
  API->>API: workspace.plan = pro
  Note over API: Limits enforced on write → 402 {code: plan_limit, resource, limit}
```

## 5. API surface

Auto-generated OpenAPI/Swagger at `/api/docs/` (schema at `/api/schema/`). Main groups under `/api/w/{slug}/`: `projects`, `issues` (+`move`, `history`, `transitions`), `sprints` (+`start`, `close`, `burndown`), `statuses`, `transitions`, `columns`, `labels`, `comments`, `attachments`, `saved-filters`, `members`, `invitations`, `audit-log`, `webhooks`, `webhook-deliveries`, `notifications`, `dashboard`, `search`, `reports/weekly`, `billing/*`. Public: `auth/*`, `invitations/{token}`, `billing/stripe-webhook`.

## 6. Security notes

- JWT auth; auth endpoints rate-limited. Production refuses to boot with the default `SECRET_KEY`.
- Passwords validated and hashed by Django; emails normalised to lower-case.
- Attachments are never served from a public `/media` URL; downloads require membership, add `nosniff`, and executable extensions are rejected.
- Webhook targets are checked against private/loopback/link-local ranges (SSRF) and redirects are not followed.
- Stripe webhooks require a valid signature in production; unsigned events are rejected.
- Secure cookies, clickjacking header and proxy-SSL settings are on when `DEBUG=0`; HSTS and SSL redirect are env-controlled.
