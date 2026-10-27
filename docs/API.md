# API contract

Application routes accept `Authorization: Bearer <session token>`. A session token comes from `POST /api/auth/signup` (creates an organization and its first admin) or `POST /api/auth/login` (email + password). Every session belongs to one organization, and every route reads and writes only that organization's data: another organization's account, resource or member is reported as `404`. There is no shared or global token. No secrets are bundled into frontend assets. Swagger UI is available at `/docs`; use its Authorize button with a session token.

Roles are `admin` and `member`. Admins can add and remove members and rename the organization; members can use everything else.

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | Database connectivity check; no token required |
| POST | `/api/auth/signup` | `{organization, email, password, name?}` → creates the organization and its admin, returns a session token. Password 8+ characters |
| POST | `/api/auth/login` | `{email, password}` → session token (5 wrong passwords lock the email for 10 minutes) |
| GET | `/api/auth/me` / POST `/api/auth/logout` | Current member, role and organization / end the session |
| GET, POST | `/api/members` | List the organization's members / add a member with a password and role (admin only) |
| DELETE | `/api/members/{id}` | Remove a member (admin only; not yourself, not the last admin) |
| GET, POST | `/api/accounts` | List cloud accounts with live totals / add an account (`mode`: `demo`, `aws`, `azure`, `aws_emu`, `azure_emu` or `import`; `aws`/`azure` take real `credentials` and `aws_emu`/`azure_emu` take the published sandbox credentials from `backend/app/emulator_data.py`; credentials are encrypted and never returned) |
| PATCH | `/api/accounts/{id}` | Rename, set or clear `budget_usd`, rotate `credentials` |
| POST | `/api/accounts/{id}/test` | Check that the stored credentials work and match the account |
| POST | `/api/accounts/{id}/sync` | Run the account's collector now |
| GET | `/api/accounts/{id}/syncs` | Recent sync runs |
| GET | `/api/resources/{id}/history` | History snapshots for one resource |
| GET | `/api/savings` | Savings pipeline and ledger of implemented changes |
| GET, PUT | `/api/organization` | Organization name, settings, members and your role / rename (admin only) |
| POST | `/api/ask` | Plain-language question answered from live data; uses the AI router when AI is configured |
| POST | `/api/ai/monitor-diagnosis`, `/api/ai/report-narrative`, `/api/ai/forecast`, `/api/ai/approval-assist/{id}`, `/api/ai/anomaly/{id}` | Optional AI drafts; `503` when AI is not configured |
| GET | `/api/forecast` | Spend forecast from metric history |
| DELETE | `/api/accounts/{id}` | Remove an account and its resources |
| GET | `/api/dashboard` | Multi-cloud totals by cloud, account and environment |
| GET | `/api/cloud-services` | Spend by service (last 3 months, from the provider's cost API) and a read-only inventory of resources across services, for your organization's accounts |
| GET | `/api/comparison` | Equivalent instance prices across clouds and per-resource alternatives |
| GET | `/api/monitor` | Live health checks with fix steps
| GET | `/api/workspace` | Current inventory, findings and latest 200 audit events |
| POST | `/api/inventory` | Import/upsert or explicitly replace inventory |
| POST | `/api/seed` | Seed empty inventory or explicitly restore samples |
| GET | `/api/sample-inventory` | Download sample resource array |
| POST | `/api/scans` | Recompute findings without calling cloud APIs |
| POST | `/api/recommendations/{id}/decision` | Approve, dismiss, reopen or simulate |
| POST | `/api/explanations/{id}` | Rule explanation or optional LLM explanation |
| GET | `/api/reports/recommendations.csv` | Server-generated recommendation report |

## Inventory request

```json
{
  "resources": [
    {
      "id": "vm-demo-01",
      "name": "staging-api",
      "provider": "Azure",
      "accountId": "acct-azure-prod",
      "region": "Central India",
      "type": "Standard_D4s_v5",
      "env": "Staging",
      "owner": "Platform team",
      "cost": 140,
      "targetCost": 70,
      "cpu": 3,
      "memory": 8,
      "network": 0.2,
      "days": 30,
      "coverage": 99,
      "hours": 730,
      "critical": false
    }
  ],
  "replace": false
}
```

`accountId` is optional and must be an existing cloud account **of your organization** with the same provider. The sample inventory's `acct-...` aliases are replaced by your own sample accounts, created on demand. Resources without it appear as "Unassigned". `provider` is `AWS`, `Azure` or `GCP`.

The UI accepts the inner resource array as a JSON file and wraps it automatically. CPU and memory are P95 summaries; cost and targetCost are monthly USD compute estimates for the same period/basis. Network is MB/day. Coverage is a percentage. Memory may be null, which blocks savings recommendations. Zero/negative costs are not fabricated: non-negative input values are required. A zero target cost needs collector validation before any real rightsizing use.

`replace=false` upserts the supplied IDs. `replace=true` removes IDs absent from the request; this does not erase audit history. Changes to any field on an existing resource invalidate its approval and increase its recommendation version. Unchanged records retain their decisions. IDs with `/` are accepted; clients should URL-encode path parameters.

## Decision request

Read the current finding from `/api/workspace` first:

```json
{
  "action": "approve",
  "expected_version": 1,
  "expected_generation": "COPY-THE-ACTUAL-UUID-FROM-THE-FINDING",
  "reviewer": "Srikanth"
}
```

The generation value in the example is descriptive: replace it with the exact returned 36-character UUID. A generation protects against deleting and reimporting a resource with the same ID; a version protects against updates to its evidence/status. The backend rejects stale decisions with HTTP 409.

Allowed transitions:

| From | Action | To | Additional requirement |
|---|---|---|---|
| Pending | approve | Approved | Positive estimated savings and non-empty reviewer label |
| Pending | dismiss | Dismissed | Finding must be actionable or a telemetry review |
| Approved / Simulated | implement | Implemented | Writes a savings-ledger entry; cannot be reopened |
| Approved | simulate | Simulated | Current generation and version |
| Approved / Simulated / Dismissed | reopen | Pending | Current generation and version |

Healthy resources cannot be approved. A reviewer name is an audit label; the authenticated member's email is recorded as the actor.

## Errors

| Status | Meaning |
|---|---|
| 401 | Missing, invalid or expired session; wrong email or password |
| 403 | Admin-only action attempted by a member |
| 429 | Too many incorrect passwords for an email |
| 404 | Resource, recommendation, account or member not found (including ones that belong to another organization) |
| 409 | Stale version/generation, invalid state transition, duplicate email, organization name or account |
| 413 | Request body too large |
| 422 | Invalid inventory, action request, email or password |
| 502 | Optional AI provider could not return an explanation |
| 503 | Database connection/schema error |

## AI configuration

LLM_API_KEY and LLM_MODEL must both be set for external explanation calls. LLM_BASE_URL must be an HTTPS OpenAI-compatible base URL, for example `https://api.openai.com/v1`. The server appends `/chat/completions`. Set a model that your chosen provider/account supports. HTTP redirects are not followed. API keys never go to the browser or into audit records.

Only provider, environment, CPU, memory, observation days, metric coverage, criticality and the deterministic finding are sent externally. Resource names, IDs and owner labels are omitted. Without AI configuration the same endpoint returns `source: rules`. The LLM cannot change decisions or execute actions.
