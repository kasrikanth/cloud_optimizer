# Cloud Cost Optimizer Agent — connected full-stack source

Run the frontend and backend directly on your computer. **Only PostgreSQL runs in Docker.**

| Component | Technology | Local address |
|---|---|---|
| Frontend | JavaScript + Vite | http://localhost:5173 |
| Backend | Python + FastAPI | http://127.0.0.1:8000 |
| API documentation | Swagger UI | http://127.0.0.1:8000/docs |
| Database | PostgreSQL 17, Docker Compose | 127.0.0.1:5433 |

The dashboard is connected to the API. Organizations, users, inventory, findings, decisions, scans and audit events persist in PostgreSQL. There is no browser-only fallback database.

## Included features

- **Multiple organizations.** Anyone can create an organization on the sign-in page and becomes its admin. Users sign in with email and password. Each organization has its own cloud accounts, credentials, inventory, recommendations, savings ledger, audit log and members, and cannot see another organization's data.
- Two roles: `admin` (adds and removes members, renames the organization) and `member`.
- Multiple AWS, Azure and GCP accounts, each optimized separately.
- Multi-cloud dashboard, cloud service comparison and a live monitor/troubleshooter with fix steps.
- Live read-only AWS and Azure collectors with encrypted credentials, scheduled sync and a no-credentials demo mode.
- Metric history, confidence on every recommendation, anomaly detection and per-account budgets.
- A savings ledger that verifies implemented changes against later data.
- Executive report, organization page and "Ask Stratus" (answers from your own data).
- Idle VM, oversized VM, after-hours scheduling and telemetry-quality analysis in Python.
- **Emulator accounts:** "AWS Emulator" and "Azure Emulator" connection modes serve static sandbox data for an imaginary startup (`backend/app/emulator_data.py`, which also lists the fake sandbox credentials the form accepts). They show 14 days of history from the first sync so every recommendation, approval and verification step can be demonstrated, and they are labelled **Emulator** everywhere. They are not real cloud data and do not contact LocalStack or any cloud.
- **Services page (AWS):** billed spend by service for the last three months (Cost Explorer) and a read-only inventory of EBS volumes, Elastic IPs, RDS, load balancers, Lambda, DynamoDB, S3 and EC2. It is visibility only; savings analysis still covers VMs. Needs extra read-only IAM permissions, listed on the page.
- Evidence and estimated savings displayed in the dashboard.
- Approve, dismiss, reopen and simulate workflows with server-side state checks.
- Updated resource data invalidates that resource's previous approval.
- Version checks reject decisions based on an outdated recommendation.
- Validated JSON inventory import, sample inventory and server-generated CSV export.
- Database migrations, durable audit records and API-token authentication.
- Optional OpenAI-compatible LLM explanations; deterministic explanation fallback without an API key.

**Execution remains a dry run.** Stratus never changes a cloud resource. Live AWS and Azure collectors are read-only and were tested with simulated cloud responses, not a customer account. GCP is import or demo only. Costs are approximate on-demand list prices, so verified savings mean "the instance cost fell", not "the invoice fell". Demo accounts are synthetic. This is a local single-admin MVP, not a multi-tenant production deployment.

## Folder map

| Folder / file | Purpose |
|---|---|
| `frontend/` | Connected dashboard, API client, Vite configuration and npm lockfile |
| `backend/app/` | FastAPI routes, models, schemas, rules, services, organization scoping (`tenant.py`) and sample data |
| `backend/alembic/` | Versioned database migrations |
| `backend/tests/` | API workflow, validation and rule tests |
| `docker-compose.yml` | PostgreSQL service only |
| `scripts/setup.py` | Generate local database password and separate API tokens |
| `docs/END_TO_END.md` | The complete flow from setup to verified savings, with a demo script |
| `docs/API.md` | API routes and workflow contract |
| `docs/ARCHITECTURE.md` | Runtime flow, database and design choices |
| `docs/VERIFICATION.md` | Checks performed and environment limitations |
| `.env.example` | Server and database configuration template |

## Prerequisites

- Python 3.12 recommended.
- Node.js 22.12+ or 24 and npm.
- Docker Desktop on Windows/macOS, or Docker Engine with the Compose plugin on Linux.
- Free local ports 5173, 8000 and 5433.

Extract the ZIP first and open terminals in the extracted `cloud-cost-optimizer` folder. Keep Docker running.

## Windows PowerShell setup

### 1. Configure and start PostgreSQL

Run from the project root:

```powershell
py -3.12 scripts/setup.py
docker compose up -d postgres
docker compose ps
```

Wait until the database shows **healthy**. If you do not have the Windows `py` launcher, use your Python 3.12 `python` command instead.

The setup script creates a root `.env` with generated secrets. It will refuse to overwrite an existing `.env`. Do not share it or commit the file. There are no API tokens to copy: you create an organization and sign in with an email and password in the app.

### 2. Start the backend — terminal A

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

These commands use the virtual environment directly, so PowerShell script activation is not required. Leave this terminal running.

### 3. Start the frontend — terminal B

Open another terminal at the project root:

```powershell
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173 and choose **Create an organization** (name, work email, password of 8+ characters). You become that organization's admin; add teammates under Organization → Members. Then use **Load sample inventory** on the dashboard to try the sample data. The frontend proxy forwards `/api` to the host backend on port 8000. **Do not put tokens in frontend environment variables.**

## Linux / macOS setup

From the project root:

```bash
python3 scripts/setup.py
docker compose up -d postgres
docker compose ps
```

After PostgreSQL becomes healthy, terminal A:

```bash
cd backend
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.lock.txt
./.venv/bin/python -m alembic upgrade head
./.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal B, starting at the project root:

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173 and create an organization, as above.

## Verify the connection

0. If you are upgrading an existing database, run `python -m alembic upgrade head` again. Migration 0004 moves the existing data into one organization (named after the old organization profile) that has no users yet: on the sign-in page choose **Create an organization** and enter that exact name to claim it as its admin. Existing sessions end and everyone signs in again.
1. Visit http://127.0.0.1:8000/health. It should return `status: ok`, `database: postgresql`, and `execution_mode: dry-run`.
2. After **Load sample inventory**, the dashboard should show 12 sample resources and 8 findings. Estimated potential is **$1,293/month** from a **$4,318/month** illustrative compute run rate.
3. Review `checkout-staging-01`, enter a reviewer label and approve it.
4. Go to Approvals, review it and simulate execution.
5. Refresh the page or restart FastAPI: the decision and audit events remain in PostgreSQL.
6. Import `docs/sample_inventory.json` from Cloud accounts → **Import JSON** to test the import pipeline.

The reviewer label is descriptive; the signed-in member's email is recorded as the actor in the audit log. Roles are limited to admin and member, there is no email verification or password reset (an admin sets passwords for members they add), and there is no single sign-on. Those are future production work.

## Database configuration

The backend runs on the host, so its connection string uses **127.0.0.1:5433**, not the Compose hostname `postgres:5432`.

`docker-compose.yml` reads `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_PORT` from the root `.env`. FastAPI reads `DATABASE_URL` from that same file regardless of your terminal's working directory. If you change the port, credentials or database name, update both the Compose variables and `DATABASE_URL` consistently. URL-encode special characters in manually chosen URL passwords; generated passwords are URL-safe.

PostgreSQL initialization variables apply when a new volume is created. Editing `.env` does not change an existing database user's password. Change an existing password using SQL before updating the connection URL. Keep the same Compose project name and volume when restarting.

Inspect database health/logs:

```bash
docker compose logs postgres
docker compose exec postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Inside psql, `\dt` lists tables and `\q` exits.

## Stop and restart

- Press Ctrl+C in frontend and backend terminals.
- Run `docker compose stop postgres` to stop only the database.
- Run `docker compose up -d postgres` to start it again.
- Start FastAPI and Vite with the same commands above. Reinstallation and reseeding are unnecessary.

The named database volume survives container stops and `docker compose down`. Deleting that volume destroys its data. The sample-restore button replaces inventory and reopens decisions but deliberately retains audit and integration history.

## Tests and builds

From `backend`, using the relevant venv Python:

```bash
python -m pytest -q
```

Use `.\.venv\Scripts\python.exe -m pytest -q` on Windows, or `./.venv/bin/python -m pytest -q` on Linux if the venv is not activated. The locked requirements include the test dependencies.

Tests use an isolated in-memory SQLite database by default; they never use the application `DATABASE_URL`. PostgreSQL integration testing is available by setting `TEST_DATABASE_URL` to a **dedicated test database whose name ends in `_test`**. Test fixtures drop/recreate tables there. Do not point this variable at a database with valuable data.

Example PostgreSQL test database, using the default Compose credentials:

```bash
docker compose exec postgres createdb -U optimizer cloud_optimizer_test
```

Set `TEST_DATABASE_URL=postgresql+psycopg://optimizer:YOUR_PASSWORD@127.0.0.1:5433/cloud_optimizer_test` in your terminal environment, then run pytest. The test command is the same on either database.

From `frontend`:

```bash
npm run check
npm run build
npm run preview
```

Preview is at http://localhost:4173 and also proxies the local backend. The Vite build creates `frontend/dist`; serve those assets behind a production web server/reverse proxy when you deploy later. Vite preview is for local checking.

## Optional integrations

- **AI features** use the OpenAI key and model from the root `.env` only (`LLM_API_KEY`, `LLM_MODEL`, optional `LLM_BASE_URL`; leave the key empty to disable AI). Restart FastAPI after editing. Features: Ask Stratus (the model picks from the built-in data handlers), monitor diagnosis, AI executive summary, approval assist, anomaly explanation, spend-forecast explanation, and finding explanations. The rules still compute every figure, status and risk; the model only routes, explains and drafts, and has no write tools. Without a key everything falls back to the deterministic behavior. Resource names, owners and metrics are sent to the provider when you use these features. Calls are limited to 30 per minute per backend process.
- Cloud account credentials are not needed for the sample workflow. Actual telemetry collectors and execution adapters are not included.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Backend refuses startup due to missing API tokens | Run `scripts/setup.py` from the root and check the root `.env` |
| Database unavailable/schema missing | Check Docker health and run `python -m alembic upgrade head` from backend |
| PostgreSQL password authentication failed | Ensure the password in the existing volume matches `.env`; changing initialization variables does not rotate existing passwords |
| Cannot reach backend | Keep uvicorn running on port 8000; check `frontend/vite.config.js` and optional `frontend/.env.local` |
| Incorrect email or password | Check the email and password. Ask an admin of your organization to remove and re-add you if the password is lost (there is no reset yet) |
| Too many incorrect attempts | Wait 10 minutes, or restart the backend |
| `Database unavailable or schema missing` after pulling this version | Run `python -m alembic upgrade head` from `backend` (migration 0004 adds organizations and users) |
| Decision returns 409 | Evidence or status changed; refresh and review the latest recommendation |
| Port 5433 already used | Change both `POSTGRES_PORT` and the port in `DATABASE_URL` before starting |
| npm reports unsupported Node version | Install Node 22.12+ or 24 |
| Import fails | Match the sample JSON field names/types; maximum 500 resources and 1 MB via frontend |
| CORS error with another frontend origin | Update `CORS_ORIGINS` in root `.env` and restart the backend |

For an externally hosted frontend, configure an HTTPS API origin using `VITE_API_BASE_URL` at build time, CORS on the backend, and a trusted reverse proxy with TLS. The local proxy settings alone do not make the backend reachable on another computer.
