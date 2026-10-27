# Verification

Completed checks for this source package:

| Check | Result |
|---|---|
| Python compilation | Passed |
| API, rule, platform, collector and tenancy tests | 58 passed using isolated in-memory SQLite |
| Frontend JavaScript syntax checks | Passed |
| Vite production build | Passed |
| Alembic migration upgrade | Passed against an isolated SQLite file. Migration 0004 (multi-organization) was also verified on a clone of a real PostgreSQL database |
| Alembic model/migration consistency check | No new upgrade operations detected |
| PostgreSQL offline migration SQL generation | Passed |
| Compose YAML | Parsed; PostgreSQL is the only service and its host port binds to loopback |
| Real HTTP smoke test through Vite proxy | Passed: HTML, authenticated API, inventory, approval persistence and CSV export |

Tests cover authentication and session scope, password login and lockout, organization roles, tenant isolation (`backend/tests/test_tenancy.py`: one organization cannot see or change another's data, and the same account or resource id can exist in two organizations), seed protection, current findings, invalid state transitions, stale versions, approval invalidation after input changes, atomic validation failures, telemetry gates, critical/production resource protection, restore behavior, CSV formula escaping, explanation fallback and slash-containing resource IDs. A delete/reimport test verifies that an old generation cannot approve a new recommendation with the same ID.

The host environment used Python 3.12.14 and Node 24.22.1. The package includes the tested Python dependency resolution and npm package lockfile. The test run emitted a Starlette notice that its current httpx test adapter is deprecated; all tests passed.

## Verification limits

Docker and a runnable native PostgreSQL service were unavailable in the original build environment (migration 0004 was later checked on a clone of a real PostgreSQL database, but the full test suite still runs on SQLite). The actual Compose container, PostgreSQL advisory/row-lock behavior and PostgreSQL persistence across container restarts were **not executed here**. Follow the README to start the supplied container and optionally run the same API tests using a dedicated PostgreSQL `_test` database.

The optional external LLM path was not called against a live provider. Sign-in has no email verification or password reset, sign-up is open, and rate limiting is in memory per process; none of these were load- or abuse-tested. **The live AWS and Azure collectors were tested only against simulated cloud responses** (fake boto3 clients and a mocked ARM API); no real AWS or Azure account was connected, and no resource mutation was performed. Run Test and Sync now against a non-production account before relying on them. The demo collector, sync, history, confidence, anomaly, budget, ledger and credential-vault logic are covered by automated tests, and the earlier shared-code sign-in, accounts, demo sync, approve and implement, savings and Ask flows were exercised in the browser. Browser UI interactions were not rerun for this downloadable full-stack variant; the frontend build and actual HTTP proxy integration were verified. The earlier static preview remains a separate application.
