# API Reference (complete)

Base URL (local): `http://127.0.0.1:8000`. The browser reaches it through the Vite proxy as `/api/...`.
Interactive docs: `http://127.0.0.1:8000/docs`. Source of truth: `backend/app/main.py`; schemas: `backend/app/schemas.py`.

**Multi-organization:** every user belongs to one organization. Every route below reads and writes only the signed-in organization's data. An id that belongs to another organization is answered with `404`, exactly as if it did not exist.

## Conventions

| Item | Detail |
|---|---|
| Auth header | `Authorization: Bearer <token>` |
| **Member auth** | A session token from `/api/auth/signup` or `/api/auth/login`. Required on every route except `/health`, signup and login |
| **Admin auth** | A member whose role is `admin`. Needed to add or remove members and to rename the organization (otherwise `403`) |
| Content type | JSON in and out, except the CSV export |
| Body limit | POST bodies over 2 MB return `413` |
| Response headers | `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` |
| Errors | `{"detail": "message"}`. `401` bad or missing token or wrong email/password, `403` admin-only action, `404` not found (or belongs to another organization), `409` conflict or stale, `413` body too large, `422` validation, `429` too many wrong passwords, `502` LLM provider down, `503` database unavailable |
| Write safety | Every write takes a PostgreSQL advisory lock per organization, so one organization's writes are serialized and others are not blocked |
| Execution | Always `dry-run`. No endpoint changes a cloud resource |

### Resource object (used by import)
Extra fields are rejected (`extra=forbid`).

| Field | Type / rule |
|---|---|
| `id` | string 1–160, `^[A-Za-z0-9][A-Za-z0-9._:/-]*$` |
| `name` | string 1–160 |
| `provider` | `AWS` \| `Azure` \| `GCP` |
| `accountId` | optional string ≤36; must be one of your organization's cloud accounts and match the resource's provider |
| `region`, `type`, `owner` | string 1–160 |
| `env` | `Development` \| `Staging` \| `Production` |
| `cost`, `targetCost` | number 0–10,000,000 (USD/month) |
| `cpu` | P95 %, 0–100 |
| `memory` | P95 %, 0–100, **or `null`** |
| `network` | MB/day, ≥ 0 |
| `days` | int 0–3650 (observation window) |
| `coverage` | % 0–100 |
| `hours` | 0–744 (run hours/month) |
| `critical` | strict boolean |

Inventory body: `{"resources": [ ...1 to 500 items, unique ids... ], "replace": false}`.

### Finding object (computed by `rules.py`, returned inside workspace rows)
`kind`: Review telemetry, Idle resource, Oversized resource, After-hours usage, Healthy.
`action`: Collect more data, Stop VM, Resize VM, Schedule downtime, Keep monitoring.
Also `saving` (USD/month, integer), `risk` (Low, Medium, High, Review, None) and `reason`.

---

## Summary

| # | Method | Endpoint | Auth | Operation | Feature |
|---|---|---|---|---|---|
| 1 | GET | `/health` | none | Fetch | Health check |
| 2 | POST | `/api/auth/signup` | none | **Create** organization, admin, session | Create an organization |
| 3 | POST | `/api/auth/login` | none | **Create** session + audit | Sign in |
| 4 | GET | `/api/auth/me` | Member | Fetch | Session check |
| 5 | POST | `/api/auth/logout` | Member | **Delete** session | Sign out |
| 6 | GET | `/api/accounts` | Member | Fetch | Cloud accounts page |
| 7 | POST | `/api/accounts` | Member | **Create** | Add cloud account |
| 8 | PATCH | `/api/accounts/{id}` | Member | **Update** | Edit account / budget / credentials |
| 9 | DELETE | `/api/accounts/{id}` | Member | **Delete** | Remove account |
| 10 | POST | `/api/accounts/{id}/test` | Member | Fetch (calls cloud) | Test connection |
| 11 | POST | `/api/accounts/{id}/sync` | Member | **Create/Update** | Sync now / Sync all |
| 12 | GET | `/api/accounts/{id}/syncs` | Member | Fetch | Account settings drawer |
| 13 | GET | `/api/workspace` | Member | Fetch | Opportunities, everything |
| 14 | GET | `/api/dashboard` | Member | Fetch | Multi-cloud dashboard |
| 15 | GET | `/api/comparison` | Member | Fetch | Cloud service comparison |
| 16 | GET | `/api/monitor` | Member | Fetch | Troubleshooter / Monitor, executive report |
| 17 | GET | `/api/savings` | Member | Fetch | Savings page |
| 18 | GET | `/api/resources/{id}/history` | Member | Fetch | Resource detail drawer |
| 19 | GET | `/api/organization` | Member | Fetch | Organization page |
| 20 | PUT | `/api/organization` | Admin | **Update** | Rename organization |
| 21 | POST | `/api/ask` | Member | Fetch (POST body) | Ask Stratus |
| 22 | POST | `/api/inventory` | Member | **Create/Update/Delete** | Import JSON |
| 23 | GET | `/api/sample-inventory` | Member | Fetch | Download sample template |
| 24 | POST | `/api/seed` | Member | **Create/Update/Delete** | Load / restore sample |
| 25 | POST | `/api/scans` | Member | **Update** | Run analysis |
| 26 | POST | `/api/recommendations/{id}/decision` | Member | **Update** | Approve / dismiss / reopen / simulate / implement |
| 27 | POST | `/api/explanations/{id}` | Member | Fetch (optional LLM call) | Ask backend to explain |
| 28 | GET | `/api/members` | Member | Fetch | Organization page |
| 29 | GET | `/api/reports/recommendations.csv` | Member | Fetch | Export CSV |
| 30 | POST | `/api/members` | Admin | **Create** user | Add member |
| 31 | POST | `/api/ai/monitor-diagnosis` | Member | Fetch (AI) | Monitor: "Diagnose with AI" |
| 32 | POST | `/api/ai/report-narrative` | Member | Fetch (AI) | Executive report: "Write summary with AI" |
| 33 | POST | `/api/ai/approval-assist/{id}` | Member | Fetch (AI) | Detail drawer: "Review with AI" |
| 34 | POST | `/api/ai/anomaly/{id}` | Member | Fetch (AI) | Monitor: "Explain with AI" on CPU/cost anomalies |
| 35 | GET | `/api/forecast` | Member | Fetch | Dashboard: spend forecast panel |
| 36 | POST | `/api/ai/forecast` | Member | Fetch (AI) | Dashboard: "Explain with AI" on the forecast |
| 37 | DELETE | `/api/members/{id}` | Admin | **Delete** user | Remove member |
| 38 | GET | `/api/cloud-services` | Member | Fetch | Services page: spend by service and inventory |

The web frontend calls every route except #4, #28 (the member list arrives inside #19) and #31–#36 where the UI does not expose the feature. Sessions and organizations never cross: see the tenancy rules at the top.

---

## 1. GET `/health`
- **Purpose:** Confirm the API and database are up.
- **Operation:** Fetch. Reads nothing but runs `SELECT 1`.
- **Parameters:** none.
- **Response 200:**
```json
{"status": "ok", "database": "postgresql", "execution_mode": "dry-run"}
```
- **Feature:** Setup verification and uptime checks. Not used by the UI.

## 2. POST `/api/auth/signup`
- **Purpose:** Create a new organization and its first admin, and sign in.
- **Operation:** **Creates** an `organizations` row, a `users` row (role `admin`, password stored as a scrypt hash), a `sessions` row and an audit event. If an organization with the same name already exists **and has no users** (data kept by migration 0004), the caller claims it as its admin instead.
- **Body:** `organization` (2–80, unique case-insensitively), `email` (valid, unique across all organizations), `password` (8+ characters), `name` (optional, ≤80).
- **Request:**
```json
{"organization": "Acme Corp", "email": "owner@acme.example", "password": "correct-horse-1"}
```
- **Response 200:**
```json
{"token": "k3J...random...", "expires_at": "2026-10-27T18:30:00+00:00",
 "user": {"email": "owner@acme.example", "name": "", "role": "admin"},
 "organization": {"id": "35f6cbe5-…-uuid", "name": "Acme Corp"}}
```
- **Errors:** `422` invalid email, short password or name; `409` email already registered or organization name taken.
- **Feature:** "Create an organization" on the sign-in page.

## 3. POST `/api/auth/login`
- **Purpose:** Sign in with email and password. The organization is the one the user belongs to.
- **Operation:** **Creates** a `sessions` row and an audit event "Signed in", and records `last_login_at`. Failed attempts are rate-limited per email in memory (5 in 10 minutes).
- **Body:** `email`, `password`.
- **Request:** `{"email": "owner@acme.example", "password": "correct-horse-1"}`
- **Response 200:** same shape as signup.
- **Errors:** `401` incorrect email or password (the same message for an unknown email); `429` too many attempts.
- **Feature:** Sign-in page.

## 4. GET `/api/auth/me`
- **Purpose:** Return who the token belongs to.
- **Operation:** Fetch. Reads `sessions`. Returns `admin-token` when the admin token is used.
- **Response 200:** `{"email": "alex@company.com", "role": "admin", "organization": {"id": "…", "name": "Acme"}}`
- **Feature:** Available for session checks. The frontend currently reads the email it stored at sign-in instead.

## 5. POST `/api/auth/logout`
- **Purpose:** End the current session.
- **Operation:** **Deletes** the matching `sessions` row.
- **Response 200:** `{"ok": true}`
- **Feature:** Sign-out button.

---

## 6. GET `/api/accounts`
- **Purpose:** List connected cloud accounts with live totals.
- **Operation:** Fetch. Reads `cloud_accounts` plus the computed findings.
- **Parameters:** none.
- **Response 200:**
```json
{
  "accounts": [{
    "id": "6f1c…-uuid", "name": "AWS · Production", "provider": "AWS",
    "accountRef": "111122223333", "region": "ap-south-1", "createdBy": "alex@company.com",
    "createdAt": "2026-10-26T09:00:00+00:00", "resources": 4, "monthlyCost": 1500,
    "potentialSavings": 310, "openRecommendations": 2,
    "mode": "import", "budgetUsd": 2000, "hasCredentials": false, "utilization": 75,
    "lastSyncAt": null, "lastSyncStatus": null, "lastSyncError": null
  }]
}
```
Resources with no account appear as an extra row named "Unassigned resources" with `id: null`. Credentials are never returned (`hasCredentials` only). Only the signed-in organization's accounts are listed.
- **Feature:** Cloud accounts page, account filter on Opportunities.

## 7. POST `/api/accounts`
- **Purpose:** Connect a new cloud account.
- **Operation:** **Creates** a `cloud_accounts` row and an audit event. For `demo` mode it also runs a sync at once, which creates resources, 14 days of history and recommendations. Credentials are Fernet-encrypted.
- **Body:**

| Field | Rule |
|---|---|
| `name` | required, 2–80 |
| `provider` | `Azure` \| `AWS` \| `GCP` |
| `account_ref` | required, 3–100. AWS live: 12-digit account ID. Azure live: subscription UUID |
| `region` | optional, ≤60 |
| `mode` | `demo` \| `aws` \| `azure` \| `aws_emu` \| `azure_emu` \| `import` (default `import`). AWS allows demo/aws/aws_emu/import, Azure demo/azure/azure_emu/import, GCP demo/import. `aws_emu` and `azure_emu` are the **Emulator** modes: static sandbox data from `backend/app/emulator_data.py`, labelled Emulator in the app, accepting only the published sandbox credentials (any other value returns `422`) |
| `credentials` | AWS: `access_key_id`, `secret_access_key`, `regions` (comma list, max 6). Azure: `tenant_id`, `client_id`, `client_secret`. Must be omitted for demo/import |
| `budget_usd` | optional, 0–100,000,000 |

- **Request (live AWS):**
```json
{"name": "AWS Prod", "provider": "AWS", "account_ref": "111122223333", "region": "ap-south-1",
 "mode": "aws", "budget_usd": 5000,
 "credentials": {"access_key_id": "AKIA...", "secret_access_key": "...", "regions": "ap-south-1,us-east-1"}}
```
- **Response 200:**
```json
{"id": "6f1c...-uuid", "name": "AWS Prod", "provider": "AWS", "mode": "aws", "sync": null}
```
For `demo`, `sync` is `{"status": "Success", "resources": 6, "removed": 0, "message": ""}`.
- **Errors:** `409` already connected in your organization (another organization may connect the same cloud account) or 50-account limit; `422` bad credentials or unsupported mode.
- **Feature:** Cloud accounts, "Add cloud account" drawer.

## 8. PATCH `/api/accounts/{account_id}`
- **Purpose:** Edit an account's name, budget or credentials.
- **Operation:** **Updates** the `cloud_accounts` row and writes an audit event. Only the fields you send change. `budget_usd: null` clears the budget.
- **Path:** `account_id` (UUID or sample id).
- **Body (all optional):** `name` (2–80), `budget_usd`, `credentials` (same shape as create, validated for the account's mode).
- **Request:**
```json
{"name": "AWS Production", "budget_usd": 6000}
```
- **Response 200:** `{"id": "6f1c...-uuid"}`
- **Errors:** `404` unknown account; `422` invalid credentials.
- **Feature:** Cloud accounts, account settings drawer.

## 9. DELETE `/api/accounts/{account_id}`
- **Purpose:** Remove an account.
- **Operation:** **Deletes** the account, all of its resources and their recommendations, and the stored credentials. Audit history, metric snapshots and ledger rows are kept.
- **Response 200:** `{"removedResources": 4}`
- **Errors:** `404`.
- **Feature:** Cloud accounts, "Remove" button (with confirm).

## 10. POST `/api/accounts/{account_id}/test`
- **Purpose:** Check that stored credentials can reach the cloud (read-only).
- **Operation:** Fetch. Calls AWS STS or Azure and writes nothing. Secrets are redacted from messages.
- **Response 200:**
```json
{"ok": true, "message": "Connected to AWS account 111122223333."}
```
On failure: `{"ok": false, "message": "..."}` (still HTTP 200).
- **Errors:** `404`; `409` for import-mode accounts (no collector).
- **Feature:** Cloud accounts, "Test connection".

## 11. POST `/api/accounts/{account_id}/sync`
- **Purpose:** Run the account's collector now.
- **Operation:** **Creates/updates** `resources`, `recommendations`, `metric_snapshots`, a `sync_runs` row, the ledger (verifies implemented savings), and updates `cloud_accounts.last_sync_*`. Resources no longer reported are deleted (pruned). Only material changes reset approvals. The sync result is recorded even on failure.
- **Response 200:**
```json
{"status": "Success", "resources": 6, "removed": 0, "message": ""}
```
`status` is `Success`, `Partial` (with warnings) or `Failed` (with a message; HTTP is still 200).
- **Errors:** `404`; `409` for import accounts.
- **Feature:** "Sync now" and "Sync all". The background scheduler runs the same logic every `SYNC_INTERVAL_MINUTES`.

## 12. GET `/api/accounts/{account_id}/syncs`
- **Purpose:** Last 20 sync runs for an account.
- **Operation:** Fetch from `sync_runs`.
- **Response 200:**
```json
{"runs": [{"id": "…", "trigger": "manual", "status": "Success", "resources": 6, "message": "",
           "startedAt": "2026-10-27T08:00:00+00:00", "finishedAt": "2026-10-27T08:00:02+00:00"}]}
```
- **Feature:** Account settings drawer (sync history).

---

## 13. GET `/api/workspace`
- **Purpose:** Return the whole working data set: resources, findings with decision state, audit log, last scan.
- **Operation:** Fetch from `resources`, `recommendations`, `audit_events` (latest 200), `scans`, `metric_snapshots`.
- **Response 200 (abridged):**
```json
{
  "resources": [{"id": "vm-demo-01", "name": "checkout-staging-01", "provider": "Azure", "accountId": "acct-azure-nonprod",
                 "region": "Central India", "type": "D4s_v5", "env": "Staging", "owner": "payments", "cost": 140,
                 "targetCost": 70, "cpu": 3.2, "memory": 11, "network": 0.4, "days": 30, "coverage": 99, "hours": 730, "critical": false}],
  "findings": [{"id": "vm-demo-01", "name": "checkout-staging-01", "...": "all resource fields",
                "kind": "Idle resource", "action": "Stop VM", "saving": 140, "risk": "Low", "reason": "Low P95 CPU…",
                "status": "Pending", "version": 1, "generation": "b0f1…-uuid", "reviewer": null, "source": "sample",
                "confidence": {"level": "High", "samples": 14, "consistency": 100}}],
  "log": [{"id": "…", "title": "Plan approved", "detail": "checkout-staging-01: Pending → Approved; Stop VM.", "actor": "alex@company.com", "time": "2026-10-27T08:10:00+00:00"}],
  "lastScan": "2026-10-27T08:00:00+00:00"
}
```
`confidence` appears only when `saving > 0`. The frontend must send `version` and `generation` back on decisions.
- **Feature:** Loaded after every action. Powers Opportunities, filters, detail drawer, Organization activity log.

## 14. GET `/api/dashboard`
- **Purpose:** Multi-cloud summary.
- **Operation:** Fetch (computed from stored data).
- **Response 200 (abridged):**
```json
{
  "totals": {"accounts": 4, "resources": 12, "monthlyCost": 4318, "potentialSavings": 1293, "openRecommendations": 8, "budget": 8000, "budgetedCost": 3900},
  "byProvider": [{"provider": "AWS", "accounts": 2, "resources": 6, "monthlyCost": 2100, "costShare": 49, "potentialSavings": 600, "openRecommendations": 4, "avgCpu": 22}],
  "byEnvironment": [{"env": "Production", "resources": 5, "monthlyCost": 2800}],
  "accounts": ["…same rows as GET /api/accounts…"],
  "lastScan": "2026-10-27T08:00:00+00:00",
  "trend": [{"date": "2026-10-26", "cost": 4300, "resources": 12}],
  "savings": {"funnel": {}, "counts": {}, "annualizedVerified": 0, "entries": []}
}
```
- **Feature:** Multi-cloud Dashboard (Overview), also the Executive report.

## 15. GET `/api/comparison`
- **Purpose:** Price the same VM class on AWS, Azure and GCP, and show where each of your VMs would be cheapest.
- **Operation:** Fetch. Uses bundled approximate list prices (`pricing.py`).
- **Response 200 (abridged):**
```json
{
  "classes": [{"id": "gp-4-16", "family": "General purpose", "vcpu": 4, "memoryGb": 16,
               "prices": {"AWS": {"type": "m6i.xlarge", "monthly": 140}, "Azure": {"type": "D4s_v5", "monthly": 140}, "GCP": {"type": "n2-standard-4", "monthly": 142}},
               "cheapest": "AWS", "spreadPct": 2.1}],
  "resources": [{"id": "vm-1", "name": "api-01", "account": "AWS · Production", "provider": "AWS", "type": "m6i.xlarge", "classId": "gp-4-16",
                 "listPrice": 140, "cheapest": {"provider": "AWS", "type": "m6i.xlarge", "monthly": 140}, "differencePct": 0,
                 "arm": {"type": "m7g.xlarge", "monthly": 112, "savingsPct": 20}}],
  "pricingModels": ["…"], "disclaimer": "Approximate on-demand Linux list prices…"
}
```
All figures above are illustrative. Real values come from `pricing.py`.
- **Feature:** Cloud Service Comparison page.

## 16. GET `/api/monitor`
- **Purpose:** Run live health checks and return issues with fix steps.
- **Operation:** Fetch (computed). Looks at stale data, missing telemetry, CPU/memory pressure, anomalies, failed or overdue syncs, budgets, database reachability.
- **Response 200 (abridged):**
```json
{
  "checkedAt": "2026-10-27T08:00:00+00:00", "status": "Attention",
  "counts": {"critical": 0, "warning": 2, "info": 1},
  "issues": [{"id": "resource:web-01:Stale data", "severity": "warning", "scope": "resource", "target": "web-01",
              "title": "Stale data", "detail": "Last reported 30 hours ago.", "fix": ["Check that the account sync…"]}],
  "accounts": [{"id": "…", "name": "AWS Prod", "provider": "AWS", "mode": "aws", "resources": 6, "lastReported": "…", "lastSyncAt": "…", "state": "Healthy"}],
  "pipeline": {"database": "ok", "executionMode": "dry-run", "llmConfigured": false, "syncEnabled": true,
               "syncIntervalMinutes": 60, "secretsConfigured": true, "lastScan": "…"},
  "thresholds": {"staleHours": 24, "cpuPressure": 80, "memoryPressure": 85}
}
```
- **Feature:** Troubleshooter / Monitor (auto-refresh every 30 s) and the Executive report.

## 17. GET `/api/savings`
- **Purpose:** Savings funnel and ledger.
- **Operation:** Fetch from `savings_ledger` (latest 200) and findings.
- **Response 200:**
```json
{
  "funnel": {"identified": 900, "approved": 200, "implemented": 140, "verified": 140.0},
  "counts": {"verified": 1, "awaiting": 1, "notVerified": 0},
  "annualizedVerified": 1680,
  "entries": [{"id": "…", "resourceId": "vm-demo-01", "resource": "checkout-staging-01", "action": "Stop VM", "status": "Verified",
               "baselineCost": 140, "expectedSaving": 140, "verifiedSaving": 140.0, "implementedBy": "alex@company.com",
               "implementedAt": "2026-10-20T08:00:00+00:00", "verifiedAt": "2026-10-21T08:00:00+00:00"}]
}
```
- **Feature:** Cloud Optimizer → Savings.

## 18. GET `/api/resources/{resource_id}/history`
- **Purpose:** Metric readings for one resource (up to 120, oldest first).
- **Operation:** Fetch from `metric_snapshots`. `resource_id` may contain `/`.
- **Response 200:**
```json
{"points": [{"time": "2026-10-13T08:00:00+00:00", "cpu": 3.1, "memory": 11.0, "network": 0.4, "cost": 140}]}
```
- **Feature:** CPU history chart in the resource detail drawer.

## 19. GET `/api/organization`
- **Purpose:** The signed-in organization's profile, server setting flags, members and your own role.
- **Operation:** Fetch from `organizations` and `users` (this organization only).
- **Response 200:**
```json
{"id": "35f6cbe5-…", "name": "Acme", "updatedBy": "alex@company.com", "createdAt": "2026-10-27T08:00:00+00:00", "sessionHours": 12,
 "syncEnabled": true, "syncIntervalMinutes": 60, "secretsConfigured": true, "llmConfigured": false,
 "members": [{"id": "…", "email": "alex@company.com", "name": "", "role": "admin", "createdAt": "…", "lastLoginAt": "…"}],
 "me": {"email": "alex@company.com", "role": "admin"}}
```
- **Feature:** Organization page and the header's organization name.

## 20. PUT `/api/organization`
- **Purpose:** Rename the organization.
- **Operation:** **Updates** `organizations` and writes an audit event. Admin only.
- **Body:** `name` (2–80, must not match another organization's name).
- **Request:** `{"name": "Acme Cloud Team"}`
- **Response 200:** the organization profile as in #19, without `members` and `me`.
- **Errors:** `403` not an admin; `409` name already used by another organization.
- **Feature:** Organization page, rename form.

## 21. POST `/api/ask`
- **Purpose:** Answer a plain-language question from your own data. It is a keyword router, not an LLM.
- **Operation:** Fetch. Reads data only. Topics: savings, idle, oversized, spend, health, compare, budget, impact, approval, risk, accounts, help.
- **Body:** `question` (2–300).
- **Request:** `{"question": "Which resources are idle?"}`
- **Response 200:**
```json
{"topic": "idle",
 "suggestions": ["How much can we save?", "Which resources are idle?", "…"],
 "answer": "2 idle resource(s) could save $210 per month if stopped. Confirm ownership first.",
 "items": [{"label": "checkout-staging-01", "value": "$140/mo", "detail": "CPU 3.2% · Staging · confidence High", "link": "#opportunities"}]}
```
- **Feature:** "Ask Stratus" panel on the dashboard.

---

## 22. POST `/api/inventory`
- **Purpose:** Import inventory from JSON (the Import JSON and per-account import buttons).
- **Operation:** **Creates** new resources, **updates** changed ones (resets their approval), **deletes** resources missing from the file when `replace` is true, then re-analyzes and writes an audit event and metric snapshots. Unknown `accountId` (including one that belongs to another organization) returns 422. The sample inventory's `acct-…` aliases become your organization's own sample accounts, created on demand.
- **Body:** inventory body (see conventions). Frontend limit: 500 resources, 1 MB.
- **Request:**
```json
{"replace": false,
 "resources": [{"id": "vm-100", "name": "reports-dev", "provider": "AWS", "accountId": "acct-aws-dev", "region": "ap-south-1",
                "type": "m6i.xlarge", "env": "Development", "owner": "data", "cost": 140, "targetCost": 70,
                "cpu": 4, "memory": 12, "network": 0.5, "days": 30, "coverage": 99, "hours": 730, "critical": false}]}
```
- **Response 200:**
```json
{"resources": 13, "findings": 9, "received": 1, "removed": 0, "replayed": false}
```
- **Errors:** `409`, `413`, `422` (unknown account, provider mismatch, duplicate ids, invalid fields).
- **Feature:** Cloud accounts, Import JSON. The global import uses `replace: true`; the per-account import uses `replace: false` and fills in `accountId`.

## 23. GET `/api/sample-inventory`
- **Purpose:** Return the bundled sample (12 resources) as a template.
- **Operation:** Fetch from `backend/app/sample_inventory.json`.
- **Response 200:** a JSON array of resource objects.
- **Feature:** "Download template" button.

## 24. POST `/api/seed`
- **Purpose:** Load or restore the sample inventory.
- **Operation:** **Creates** sample resources and your organization's own sample accounts. With `replace: true` it also **deletes** your other resources and **reopens** decisions. Audit history is kept.
- **Body:** `replace` (bool, default false).
- **Request:** `{"replace": false}`
- **Response 200:** `{"resources": 12, "findings": 8, "received": 12, "removed": 0, "replayed": false}`
- **Errors:** `409` if inventory exists and `replace` is false.
- **Feature:** "Load sample inventory" (empty state) and "Restore sample inventory".

## 25. POST `/api/scans`
- **Purpose:** Re-run the rules on stored inventory.
- **Operation:** **Updates** `recommendations` where findings changed (status goes back to Pending, version bumps) and inserts a `scans` row and audit event. No cloud call.
- **Body:** none.
- **Response 200:** `{"resources": 12, "findings": 8}`
- **Feature:** "Run analysis" button.

## 26. POST `/api/recommendations/{resource_id}/decision`
- **Purpose:** Move a recommendation through its workflow.
- **Operation:** **Updates** `recommendations` (status, reviewer, version), writes an audit event in one transaction. `implement` also **creates** a `savings_ledger` row.
- **Body:**

| Field | Rule |
|---|---|
| `action` | `approve` \| `dismiss` \| `reopen` \| `simulate` \| `implement` |
| `expected_version` | int ≥ 1, from `/api/workspace` |
| `expected_generation` | 36-char UUID, from `/api/workspace` |
| `reviewer` | string ≤80; **required for `approve`** |

- **Allowed transitions:**

| Action | From | To |
|---|---|---|
| approve | Pending (with saving > 0) | Approved |
| dismiss | Pending | Dismissed |
| reopen | Approved, Simulated, Dismissed | Pending |
| simulate | Approved | Simulated (dry run) |
| implement | Approved or Simulated | Implemented |

- **Request:**
```json
{"action": "approve", "expected_version": 1, "expected_generation": "b0f1c2d3-1111-4222-8333-444455556666", "reviewer": "alex@company.com"}
```
- **Response 200:** `{"status": "Approved", "version": 2, "mode": "dry-run"}`
- **Errors:** `404`; `409` stale version or generation, wrong state, healthy resource, or implemented (cannot reopen); `422` missing reviewer.
- **Feature:** Resource detail drawer buttons (Approve plan, Dismiss, Reopen, Simulate, Mark implemented).

## 27. POST `/api/explanations/{resource_id}`
- **Purpose:** Plain-English explanation of one finding.
- **Operation:** Fetch. Without LLM settings, returns the rule text. With `LLM_API_KEY`, `LLM_BASE_URL` and `LLM_MODEL` set, calls `{LLM_BASE_URL}/chat/completions` with a limited evidence set. Nothing is stored.
- **Body:** none.
- **Response 200:** `{"source": "rules", "text": "Low P95 CPU, memory and network traffic…"}` or `{"source": "llm", "text": "…"}`
- **Errors:** `404`; `502` LLM provider unavailable.
- **Feature:** "Ask backend to explain" in the detail drawer.

## 28. GET `/api/members`
- **Purpose:** List the organization's members.
- **Operation:** Fetch from `users` (this organization only).
- **Response 200:**
```json
{"members": [{"id": "…uuid", "email": "owner@acme.example", "name": "", "role": "admin", "createdAt": "2026-10-27T08:00:00+00:00", "lastLoginAt": "2026-10-27T08:00:00+00:00"}]}
```
- **Feature:** Organization page (the same list also arrives inside #19).

## 29. GET `/api/reports/recommendations.csv`
- **Purpose:** Download actionable recommendations as CSV.
- **Operation:** Fetch. Healthy resources are excluded. Values starting with `=`, `+`, `-` or `@` are prefixed with `'` to block spreadsheet formula injection.
- **Response 200:** `text/csv`, attachment `cloud-cost-recommendations.csv`:
```csv
Resource,Provider,Environment,Owner,Finding,Action,Risk,Status,Estimated monthly savings USD,Mode
checkout-staging-01,Azure,Staging,payments,Idle resource,Stop VM,Low,Pending,140,dry-run estimate
```
- **Feature:** "Export CSV" on the Dashboard and Opportunities.

---

## 30. POST `/api/members`
- **Purpose:** Add a person to the organization with a password you choose for them.
- **Operation:** **Creates** a `users` row and an audit event. Admin only.
- **Body:** `email`, `password` (8+), `name` (optional), `role` (`member` default, or `admin`).
- **Request:** `{"email": "dev@acme.example", "password": "temporary-pass-1", "name": "Dev", "role": "member"}`
- **Response 200:** `{"id": "…uuid", "email": "dev@acme.example", "role": "member"}`
- **Errors:** `403` not an admin; `409` the email already has an account in any organization; `422` invalid email or password.
- **Feature:** Organization page, "Add member".

## 37. DELETE `/api/members/{user_id}`
- **Purpose:** Remove a member. Their sessions stop working immediately.
- **Operation:** **Deletes** the `users` row and writes an audit event. Admin only.
- **Response 200:** `{"ok": true}`
- **Errors:** `403` not an admin; `404` unknown id or a member of another organization; `409` removing yourself or the last admin.
- **Feature:** Organization page, "Remove".

## 38. GET `/api/cloud-services`
- **Purpose:** Spend by service and a read-only inventory of what exists in the organization's connected AWS accounts.
- **Operation:** Fetch from `service_costs` and `cloud_assets` (this organization only). Both are filled by the AWS collector on each sync: Cost Explorer for the last three months grouped by service, plus EBS volumes, Elastic IPs, RDS instances, load balancers, Lambda functions, DynamoDB tables, S3 buckets and EC2 instances. A service the key could not read keeps its previous rows. This is visibility only; savings analysis still covers VMs.
- **Response 200 (abridged):**
```json
{"months": ["2026-09", "2026-10"], "currentMonth": "2026-10", "monthToDate": true,
 "spend": {"total": {"2026-09": 2831.0, "2026-10": 1734.0},
           "byService": [{"service": "Amazon Elastic Compute Cloud - Compute", "amounts": {"2026-09": 2100.5, "2026-10": 1250.4}, "share": 72.1}],
           "byAccount": [{"id": "6f1c…", "name": "AWS Production", "amounts": {"2026-09": 2831.0, "2026-10": 1734.0}}]},
 "inventory": {"total": 6, "byService": [{"service": "EBS Volume", "count": 2, "notAttached": 1}]},
 "assets": [{"id": "…", "accountId": "6f1c…", "account": "AWS Production", "service": "EBS Volume", "assetId": "vol-02", "name": "old-vol",
             "region": "ap-south-1", "type": "gp2", "state": "not attached", "detail": {"sizeGb": 500}}],
 "assetsTruncated": false,
 "accounts": [{"id": "6f1c…", "name": "AWS Production", "provider": "AWS", "mode": "aws", "hasSpend": true, "assetCount": 6}],
 "collectedAt": "2026-10-27T08:00:00+00:00", "note": "Spend is the provider-reported billed cost…"}
```
`assets` lists at most 500 rows. `amounts` are USD; the current month is month to date.
- **Extra IAM permissions for live AWS accounts (all read-only):** `ce:GetCostAndUsage`, `ec2:DescribeVolumes`, `ec2:DescribeAddresses`, `rds:DescribeDBInstances`, `elasticloadbalancing:DescribeLoadBalancers`, `lambda:ListFunctions`, `dynamodb:ListTables`, `s3:ListAllMyBuckets`. A missing permission only produces a sync warning. Cost Explorer must be enabled in the AWS account and AWS bills about $0.01 per Cost Explorer request.
- **Feature:** Multi-cloud Dashboard → Services.

---

## Not HTTP APIs (but part of the integration surface)

| Item | Direction | Detail |
|---|---|---|
| Background scheduler | Internal | Syncs due `demo`/`aws`/`azure` accounts every `SYNC_INTERVAL_MINUTES` (checks each minute). Each account is synced inside its own organization |
| AWS collector | App → AWS | Read-only: `ec2:DescribeInstances`, `cloudwatch:GetMetricData`, `sts:GetCallerIdentity` |
| Azure collector | App → Azure | Read-only REST with Reader and Monitoring Reader |
| LLM | App → provider | Only from #27, when configured |

---

## AI endpoints (31–34, 36) and forecast (35), plus changes to #21 and #27

All AI features read `LLM_API_KEY`, `LLM_MODEL` and optional `LLM_BASE_URL` from the server `.env` only. No request field can change them. They take no body. The model never writes data: every status, saving and risk still comes from the rules.

| Common behavior | |
|---|---|
| AI not configured | `503` "AI is not configured…" (#21 instead falls back to the keyword router) |
| Provider error, unreadable answer, or limit (30 calls/min/process) | `502` (#21 falls back to the keyword router and sets `notice`) |
| Unknown resource | `404` |

- **#21 `POST /api/ask`**: with AI on, the model chooses up to 3 existing topic handlers as tools, the handlers compute the data, and the model words a short answer. Response adds `"source": "ai" | "rules"` and `"notice"`. Unlisted tools are never run.
- **#27 `POST /api/explanations/{id}`**: unchanged contract; now uses the shared client.
- **#31** → `{"source":"ai","summary":"…","causes":[{"title","explanation","issueIds":["…"],"nextSteps":["…"]}]}`. Groups the top 20 monitor issues by probable cause. `issueIds` are filtered to real issue IDs.
- **#32** → `{"source":"ai","headline","summary":["…"],"decisions":["…"],"risks":["…"]}` from dashboard and monitor figures.
- **#33** → `{"source":"ai","blastRadius","checks":["…"],"rollback","approvalNote"}`. `409` for Healthy resources.
- **#34** → `{"source":"ai","summary","causes":[{"cause","evidence","confidence":"High|Medium|Low"}],"checks":["…"]}` from 30 readings, recent audit events, ledger entries and sync runs.
- **#35 `GET /api/forecast`** (no AI): `{"horizonDays":30,"fleet":{"sufficient","current","projected","changePct","slopePerDay","readings","confidence":"High|Medium|Low|null","coveragePct","trendedResources","totalResources","basisCurrent","basisProjected","series":[{"date","cost"}]},"accounts":[{"id","name","current","projected","budgetUsd","utilizationNow","utilizationProjected","daysToBudget","budgetStatus":"Over budget now|Likely to exceed|Close to budget|On track|No budget","coveragePct","confidence"}],"basis":"…"}`. Each resource is trended on its own `metric_snapshots` history (last 60 days, straight line) and the slopes are summed, so resources joining or leaving don't fake a jump. Resources with fewer than 3 daily readings are held flat, and `coveragePct` says how much of the run rate has a trend. `series` is the like-for-like history of those resources, and `basisProjected` is their forecast.
- **#36 `POST /api/ai/forecast`** → `{"source":"ai","summary","budgetRisks":["…"],"actions":["…"],"caveats":["…"]}`. The model explains the #35 figures and never produces its own. With too little history it answers without calling the model.
- `GET /api/monitor` issues for resources now include `resourceId`.
