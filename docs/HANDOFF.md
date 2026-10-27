# Stratus: project handoff

Give this file to another assistant (or engineer) to continue the work. It summarizes what was asked, what was built, why, how to run it, and what is still open. It is a summary, not a transcript.

Project root: `D:\hackathon\cloud-cost-optimizer-fullstack\cloud-cost-optimizer` (Windows, no git repository).

## 1. What the product is

**Stratus** is an organization workspace that finds wasted cloud spend on AWS, Azure and GCP VMs, lets people approve changes, and later **verifies** that the savings happened. It is a hackathon project for an organization (the user's email domain is easystepin.com).

Four features the user wants to offer:

1. Cloud optimizer
2. Multi-cloud dashboard
3. Cloud service comparison
4. Cloud troubleshooter / monitor

Hard rule: **execution is a dry run.** Stratus never changes a cloud resource. People make changes in their cloud; Stratus recommends, records decisions and verifies results from collected data.

## 2. How the conversation went (in order)

1. Asked what the starter application does. Answer: a FastAPI + PostgreSQL + Vite app with rules for idle/oversized VMs.
2. Asked how to show "real time" without a paid cloud account, and whether $0 billing is a problem. Answer: use free-tier/trial accounts with read-only access; savings come from utilization plus list prices, not invoices, so $0 billing is fine.
3. Asked if the app was complete. Answer: working demo, but no real collectors and no real data.
4. Asked to improve the frontend using the "impeccable" design skill (GitHub `pbakaus/impeccable`) and remove filler text. The skill was not installable here, so its principles were applied by hand: new font (Manrope), tinted neutrals, no gradients, fake chart removed, much less copy.
5. Asked for org features: a first simple sign-in with no roles (replaced later, see items 11 and 12), multiple cloud accounts, multi-cloud dashboard, service comparison, troubleshooter/monitor. Built.
6. Said the app "is not proper"; asked for end-to-end, organization focus, innovation, and a flow document. Built live AWS/Azure collectors, demo mode, history, confidence, anomalies, budgets, savings ledger, Ask Stratus, executive report, organization page, and `docs/END_TO_END.md`.
7. Asked for a document, then a simple **BRD**. A Claude Docs document was created: https://claude.ai/artifact/1tLMWnddnTdnDUwiQgk8kr ("Stratus: Business Requirements Document").
8. Asked for a tree-like left navigation for the four features. Built, then asked to **merge screens that are not required**: reduced 15 nav screens to 7.
9. Asked which APIs write to the database, and for a plain explanation of the APIs. See section 6.
10. Asked for the whole chat for another assistant: this file.
11. Asked to remove Boomi completely. Removed: the Boomi inventory endpoint and the integrations listing, the Boomi settings, the transactional outbox and `ingestion_receipts` (with `Idempotency-Key` handling), the dispatch command, `docs/BOOMI.md` and `docs/boomi_request.json`. Inventory now arrives only through the live AWS/Azure collectors, demo accounts and JSON import (GCP: JSON import or demo).
12. Asked for multiple organizations with email + password login. Built: anyone can create an organization on the sign-in page and becomes its admin; users sign in with email and password; roles are `admin` and `member`; every organization's data is isolated. The old shared static code, the shared admin token, the domain allowlist and the fixed organization name were removed. Existing single-organization data was migrated by migration 0004 into one organization with no users; signing up with that same organization name claims it. Added `backend/tests/test_tenancy.py`; the full backend suite is 58 tests passing on in-memory SQLite, and migration 0004 was verified on a clone of a real PostgreSQL database.

User preferences: wants things "proper end to end", plain explanations, honest status, fewer screens, hackathon-ready demo. Often asks for simple language.

## 3. What is built (current state)

**Sign-in and organizations:** anyone can create an organization on the sign-in page (`POST /api/auth/signup`: organization name, email, password of at least 8 characters) and becomes its admin; users sign in with email + password (`POST /api/auth/login`). Passwords are hashed with scrypt. 5 wrong passwords lock an email for 10 minutes. Server-side sessions: random tokens stored hashed, tied to a user, 12 h default (`SESSION_HOURS`). Each user belongs to exactly one organization; roles are `admin` (add/remove members, rename the organization) and `member` (everything else). Every organization has its own cloud accounts, credentials, resources, recommendations, savings ledger, audit log, history and budgets, and cannot see another's; the same AWS account id or resource id may exist in two organizations.

**Cloud accounts:** AWS, Azure, GCP. Connection modes: `aws` (live, read-only), `azure` (live, read-only), `demo` (synthetic, no credentials, 14 days of backfilled history), `import` (JSON). GCP supports demo and import only. Credentials are Fernet-encrypted with `SECRETS_KEY`, never returned by the API. Per-account monthly budget. Test connection, Sync now, scheduled sync (default hourly), sync history.

**Analysis rules (one finding per VM):** Review telemetry (under 14 days, under 95% coverage, or no memory metric) → Idle (CPU under 5%, memory under 15%, network under 1 MB/day, non-prod, non-critical) → Oversized (CPU under 30%, memory under 40%, cheaper size exists) → After-hours (dev, non-critical, over 300 h/month) → Healthy. Untagged cloud VMs count as Production, so they are never suggested for stopping.

**History and insights:** metric snapshots (90-day retention), confidence (High/Medium/Low from consistency of the rule across the last 14 readings), anomaly detection (needs 8 readings), run-rate trend, budget alerts.

**Decisions:** approve, dismiss, reopen, simulate, **implement**. Version and generation checks reject stale decisions (HTTP 409). Each decision writes an audit event.

**Savings ledger:** "Mark implemented" creates an entry; the next sync marks it Verified (VM gone, or cost at least 2% lower) or Not verified after 14 days. In a **demo** account the next sync applies the implemented change (stop, resize, schedule) to stand in for the real cloud.

**Other:** service comparison across the three clouds (approximate list prices), monitor with fix steps, executive report (printable), organization page (name, members and roles, settings, activity log), "Ask Stratus" (keyword router over live data, not an LLM), CSV export, optional LLM explanations.

**Navigation (7 screens):**

```
Cloud Optimizer             Opportunities · Savings
Multi-cloud Dashboard       Overview · Cloud accounts
Cloud Service Comparison    one screen
Troubleshooter / Monitor    one screen
Organization                one screen (settings, members, activity log)
```

Old routes redirect (`#approvals` → Opportunities with Approved filter, `#activity` → Organization, `#integrations` → Cloud accounts, and so on). The Executive report opens from a button on the dashboard.

## 4. Architecture and key files

Stack: Python 3.12 + FastAPI + SQLAlchemy + Alembic, cloud PostgreSQL over verified TLS, Vite + plain JavaScript frontend (no framework).

```
backend/app/main.py            routes, auth dependency, lifespan scheduler
backend/app/services.py        ingest (single door to the DB), analyze, decide, workspace
backend/app/rules.py           the idle / oversized / after-hours rules
backend/app/accounts.py        accounts, credential validation, sample accounts
backend/app/auth.py            password hashing (scrypt), login lockout, sessions
backend/app/tenant.py          organization scoping for every query
backend/app/vault.py           Fernet encryption of credentials
backend/app/sync.py            run a collector, ingest, record sync run, scheduler
backend/app/collectors/        aws.py (boto3), azure.py (REST/httpx), demo.py
backend/app/pricing.py         bundled list-price table and size ladders
backend/app/history.py         snapshots, confidence, anomalies, trend
backend/app/ledger.py          savings ledger and verification
backend/app/insights.py        dashboard, comparison, monitor
backend/app/ask.py             Ask Stratus
backend/app/organization.py    org profile, members, roles (admin/member)
backend/alembic/versions/      0001 initial, 0002 accounts/sessions, 0003 collectors/history/ledger/org, 0004 multi-organization
backend/tests/                 test_workflow, test_organization, test_platform, test_tenancy (58 tests)
frontend/src/app.js            app logic, routing, nav tree, drawers
frontend/src/views.js          page renderers
frontend/src/ui.js, api.js     helpers, charts, API client
docs/END_TO_END.md             full flow, security model, runbook, demo script
docs/API.md, ARCHITECTURE.md, VERIFICATION.md
```

Tables: resources, recommendations, scans, audit_events, sessions, cloud_accounts, metric_snapshots, sync_runs, savings_ledger, organization, users.

Design choices worth keeping: ingest is the only write path for inventory (one transaction: validate, upsert, snapshot, analyze, audit); routine syncs only invalidate approvals on **material** changes (type, cost, env, owner, name, region, account, criticality), not metric noise; every page is computed on request from stored data.

## 5. Running it (Windows)

```powershell
# one time, from the project root
py -3.12 scripts/setup.py            # creates .env with generated secrets (SECRETS_KEY included)
# Set DATABASE_URL in .env to the cloud PostgreSQL endpoint before migrations.
cd backend; py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# second terminal
cd frontend; npm ci; npm run dev     # http://localhost:5173
```

Create an organization on the sign-in page (or claim the migrated one by signing up with its name), then sign in with email + password. Tests: `cd backend; .\.venv\Scripts\python.exe -m pytest -q` (58 pass, in-memory SQLite). Frontend check: `npm run build`.

Historical local environment (before the cloud database switch): PostgreSQL, the backend and Vite were running locally (ports 5433, 8000, 5173). `.claude/launch.json` defines `backend` and `frontend` preview servers. The database contains test data: sample accounts and VMs, a GCP test account, a demo account "Payments (AWS demo)" and some verified ledger entries. Use Cloud accounts → Restore sample inventory or remove those accounts to clean up.

Key `.env` settings: `DATABASE_URL`, `SESSION_HOURS`, `SECRETS_KEY`, `SYNC_ENABLED`, `SYNC_INTERVAL_MINUTES`, `CORS_ORIGINS`, optional `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`. Back up `SECRETS_KEY` with the database; losing it means re-entering credentials.

## 6. APIs: what writes to the database

All routes need `Authorization: Bearer <session token>`, except sign-up and login; every query is scoped to the user's organization. Full list: `docs/API.md` and Swagger at `/docs`.

- **Inventory in:** `POST /api/inventory` (JSON import), `POST /api/accounts/{id}/sync`, `POST /api/seed`, `POST /api/scans`.
- **Decisions:** `POST /api/recommendations/{resource_id}/decision` (approve, dismiss, reopen, simulate, implement).
- **Accounts and org:** `POST /api/accounts`, `PATCH /api/accounts/{id}`, `DELETE /api/accounts/{id}`, `PUT /api/organization` (admin), member add/remove (admin), `POST /api/auth/signup`, `POST /api/auth/login`, `POST /api/auth/logout`.
- **Read-only:** all `GET` routes, `POST /api/ask`, `POST /api/explanations/{id}`, `POST /api/accounts/{id}/test`.

## 7. Known limits and what is not verified

- **Live AWS and Azure collectors were tested only against simulated responses** (fake boto3 clients, a mocked ARM API). No real cloud account was connected. First real run on a non-production account may surface bugs.
- GCP has no live collector.
- Costs are approximate on-demand list prices (`pricing.py`), compute only. "Verified" means the instance cost fell, not that the invoice fell.
- Sign-in is basic: no email verification and no password reset (an admin sets passwords for members they add), sign-up is open to anyone who can reach the API, rate limiting is in memory per process, and there is no single sign-on.
- LLM explanations were never called against a provider.
- Ask Stratus is a keyword router, not a language model.
- No git repository exists for the project.

## 8. Suggested next steps

1. Run the AWS or Azure collector against a free-tier or trial account (Test, then Sync now) and fix what breaks.
2. Add email verification, password reset and single sign-on; restrict or approve sign-ups; move rate limiting out of process memory.
3. Reconcile savings with billing exports (Cost Explorer or Cost Management).
4. Add a live GCP collector.
5. Initialize a git repository and set up CI for the test suite and frontend build.

## 9. Documents that already exist

- `docs/END_TO_END.md`: the end-to-end flow, security model, runbook and a five-minute demo script.
- Claude Docs BRD: https://claude.ai/artifact/1tLMWnddnTdnDUwiQgk8kr
- `docs/API.md`, `docs/ARCHITECTURE.md`, `docs/VERIFICATION.md`, `README.md`.

## 10. Tips for the next assistant

- Match the existing code style: dense, compact JavaScript in `frontend/src`, plain functions in the backend.
- Keep status claims honest. The user values clear statements of what was and was not verified.
- After backend changes, restart uvicorn (it runs without `--reload`). Vite hot-reloads.
- Run the 58 tests and `npm run build` before finishing.
- Keep the 7-screen navigation unless the user asks otherwise.
