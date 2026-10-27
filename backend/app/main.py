import asyncio
import csv
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from .config import get_settings
from .db import get_db
from .collectors import SIMULATED_MODES
from .accounts import account_rows, create_account, get_account, remove_account, update_account
from . import ai_features, cloud_services
from .llm import AIError, GUARD, complete as llm_complete, configured
from .auth import Principal, authenticate, hash_token, open_session, principal_for
from .forecast import forecast as spend_forecast
from .history import resource_history
from .insights import comparison, dashboard, monitor
from .ledger import summary as savings_summary
from .organization import add_member, create_organization, get_org, members as org_members, organization as org_profile, remove_member, rename as org_rename
from .models import Recommendation, Resource, UserSession, utcnow
from .schemas import AccountInput, AccountUpdate, AskInput, DecisionInput, InventoryInput, LoginInput, MemberInput, OrganizationUpdate, SeedInput, SignupInput
from .services import analyze, audit, decide, ingest, workspace, writer_lock
from .sync import recent_runs, run_sync, scheduler, test_connection
from .tenant import bind, org_of

settings = get_settings()


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(scheduler()) if settings.sync_enabled else None
    yield
    if task:
        task.cancel()


app = FastAPI(lifespan=lifespan, title='Cloud Cost Optimizer API', version='1.0.0', description='Multi-organization workspace with email + password sign-in. Each organization sees only its own cloud accounts and data. All cloud actions are dry runs.')
app.add_middleware(CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(',')],
    allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
    # ngrok-skip-browser-warning lets a frontend on another machine bypass ngrok's free-tier interstitial page.
    allow_headers=['Authorization', 'Content-Type', 'ngrok-skip-browser-warning'])
bearer = HTTPBearer(auto_error=False)
DB = Annotated[Session, Depends(get_db)]


def current(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)], db: DB) -> Principal:
    """The signed-in member. Binds this request's database session to the member's organization."""
    principal = principal_for(db, credentials.credentials) if credentials else None
    if not principal:
        raise HTTPException(401, 'Please sign in again.', headers={'WWW-Authenticate': 'Bearer'})
    bind(db, principal.org_id)
    return principal


def org_admin(principal: Annotated[Principal, Depends(current)]) -> Principal:
    if not principal.is_admin:
        raise HTTPException(403, 'Only an organization admin can do this.')
    return principal


Member = Annotated[Principal, Depends(current)]
Admin = Annotated[Principal, Depends(org_admin)]


@app.middleware('http')
async def request_limits(request: Request, call_next):
    if request.method == 'POST':
        content_length = request.headers.get('content-length', '0')
        if not content_length.isdigit() or int(content_length) > 2_000_000:
            return JSONResponse({'detail': 'Request body exceeds 2 MB'}, 413)
        if len(await request.body()) > 2_000_000:
            return JSONResponse({'detail': 'Request body exceeds 2 MB'}, 413)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    # SQL exception strings can contain connection details and inventory values.
    return JSONResponse({'detail': 'Database unavailable or schema missing. Check PostgreSQL and run alembic upgrade head.'}, 503)


@app.get('/health')
def health(db: DB):
    db.execute(text('SELECT 1'))
    return {'status': 'ok', 'database': db.bind.dialect.name, 'execution_mode': 'dry-run'}


def session_response(db: Session, user):
    token, expires = open_session(db, user, settings.session_hours)
    org = get_org(db)
    return {'token': token, 'expires_at': expires.isoformat(),
            'user': {'email': user.email, 'name': user.name, 'role': user.role}, 'organization': {'id': org.id, 'name': org.name}}


@app.post('/api/auth/signup')
def signup(payload: SignupInput, db: DB):
    """Create an organization and its first admin, then sign in."""
    user = create_organization(db, payload.organization, payload.email, payload.password, payload.name)
    user.last_login_at = utcnow()
    bind(db, user.org_id)
    audit(db, 'Organization created', f'{payload.organization} created by {user.email}.', user.email)
    result = session_response(db, user)
    db.commit()
    return result


@app.post('/api/auth/login')
def login(payload: LoginInput, db: DB):
    user = authenticate(db, payload.email.lower(), payload.password)
    bind(db, user.org_id)
    audit(db, 'Signed in', f'{user.email} signed in.', user.email)
    result = session_response(db, user)
    db.commit()
    return result


@app.get('/api/auth/me')
def me(p: Member, db: DB):
    org = get_org(db)
    return {'email': p.email, 'role': p.role, 'organization': {'id': org.id, 'name': org.name}}


@app.post('/api/auth/logout')
def logout(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)], db: DB, p: Member):
    row = db.get(UserSession, hash_token(credentials.credentials)) if credentials else None
    if row:
        db.delete(row)
        db.commit()
    return {'ok': True}


@app.get('/api/accounts')
def list_accounts(p: Member, db: DB):
    return {'accounts': account_rows(db, workspace(db)['findings'])}


@app.post('/api/accounts')
def add_account(payload: AccountInput, db: DB, p: Member):
    writer_lock(db)
    account = create_account(db, payload, p.email)
    audit(db, 'Cloud account added', f'{account.name} ({account.provider} {account.account_ref}, {account.mode}) connected by {p.email}.', p.email)
    sync = run_sync(db, account.id, 'manual', p.email) if account.mode in SIMULATED_MODES else None
    db.commit()
    return {'id': account.id, 'name': account.name, 'provider': account.provider, 'mode': account.mode, 'sync': sync}


@app.patch('/api/accounts/{account_id}')
def edit_account(account_id: str, payload: AccountUpdate, db: DB, p: Member):
    writer_lock(db)
    account = update_account(db, account_id, payload)
    changed = [k for k in ('name', 'budget_usd', 'credentials') if k in payload.model_fields_set]
    audit(db, 'Cloud account updated', f'{account.name}: {", ".join(changed) or "no changes"} updated by {p.email}.', p.email)
    db.commit()
    return {'id': account.id}


@app.post('/api/accounts/{account_id}/test')
def test_account(account_id: str, db: DB, p: Member):
    return test_connection(db, account_id)


@app.post('/api/accounts/{account_id}/sync')
def sync_account(account_id: str, db: DB, p: Member):
    result = run_sync(db, account_id, 'manual', p.email)
    db.commit()
    return result


@app.get('/api/accounts/{account_id}/syncs')
def account_syncs(account_id: str, db: DB, p: Member):
    return {'runs': recent_runs(db, account_id)}


@app.delete('/api/accounts/{account_id}')
def delete_account(account_id: str, db: DB, p: Member):
    writer_lock(db)
    name = get_account(db, account_id).name
    removed = remove_account(db, account_id)
    audit(db, 'Cloud account removed', f'{name} removed by {p.email}; {removed} resource(s) and their recommendations deleted.', p.email)
    db.commit()
    return {'removedResources': removed}


@app.get('/api/resources/{resource_id:path}/history')
def get_resource_history(resource_id: str, db: DB, p: Member):
    return {'points': resource_history(db, resource_id)}


@app.get('/api/savings')
def get_savings(db: DB, p: Member):
    return savings_summary(db, workspace(db)['findings'])


@app.get('/api/organization')
def get_organization(db: DB, p: Member):
    return {**org_profile(db), 'members': org_members(db), 'me': {'email': p.email, 'role': p.role}}


@app.put('/api/organization')
def update_organization(payload: OrganizationUpdate, db: DB, p: Admin):
    result = org_rename(db, payload.name, p.email)
    audit(db, 'Organization renamed', f'Organization name set to "{payload.name}" by {p.email}.', p.email)
    db.commit()
    return result


@app.get('/api/members')
def list_members(db: DB, p: Member):
    return {'members': org_members(db)}


@app.post('/api/members')
def create_member(payload: MemberInput, db: DB, p: Admin):
    user = add_member(db, payload.email, payload.password, payload.name, payload.role)
    audit(db, 'Member added', f'{user.email} added as {user.role} by {p.email}.', p.email)
    db.commit()
    return {'id': user.id, 'email': user.email, 'role': user.role}


@app.delete('/api/members/{user_id}')
def delete_member(user_id: str, db: DB, p: Admin):
    user = remove_member(db, user_id, p.user_id)
    audit(db, 'Member removed', f'{user.email} removed by {p.email}.', p.email)
    db.commit()
    return {'ok': True}


@app.post('/api/ask')
def ask(payload: AskInput, db: DB, p: Member):
    return ai_features.ask(db, payload.question)


@app.post('/api/ai/monitor-diagnosis')
def ai_monitor_diagnosis(db: DB, p: Member):
    return ai_features.diagnose_monitor(db)


@app.post('/api/ai/report-narrative')
def ai_report_narrative(db: DB, p: Member):
    return ai_features.report_narrative(db)


@app.post('/api/ai/approval-assist/{resource_id:path}')
def ai_approval_assist(resource_id: str, db: DB, p: Member):
    return ai_features.approval_assist(db, resource_id)


@app.post('/api/ai/forecast')
def ai_forecast(db: DB, p: Member):
    return ai_features.forecast_narrative(db)


@app.post('/api/ai/anomaly/{resource_id:path}')
def ai_anomaly(resource_id: str, db: DB, p: Member):
    return ai_features.explain_anomaly(db, resource_id)


@app.get('/api/dashboard')
def get_dashboard(db: DB, p: Member):
    return dashboard(db)


@app.get('/api/forecast')
def get_forecast(db: DB, p: Member):
    return spend_forecast(db)


@app.get('/api/cloud-services')
def get_cloud_services(db: DB, p: Member):
    return cloud_services.overview(db)


@app.get('/api/comparison')
def get_comparison(db: DB, p: Member):
    return comparison(db)


@app.get('/api/monitor')
def get_monitor(db: DB, p: Member):
    return monitor(db)


@app.get('/api/workspace')
def get_workspace(db: DB, p: Member):
    return workspace(db)


@app.post('/api/inventory')
def import_inventory(payload: InventoryInput, db: DB, p: Member):
    result = ingest(db, payload, actor=p.email)
    db.commit()
    return result


def load_sample():
    return json.loads((Path(__file__).parent / 'sample_inventory.json').read_text())


@app.get('/api/sample-inventory')
def sample_inventory(p: Member):
    return load_sample()


@app.post('/api/seed')
def seed_inventory(payload: SeedInput, db: DB, p: Member):
    writer_lock(db)
    if db.scalar(select(Resource.id).where(Resource.org_id == org_of(db)).limit(1)) and not payload.replace:
        raise HTTPException(409, 'Inventory already exists. Explicit replace=true is required to restore the sample.')
    sample = load_sample()
    result = ingest(db, InventoryInput(resources=sample, replace=payload.replace), source='sample', actor=p.email)
    # Restore must also reopen decisions for unchanged sample records.
    if payload.replace:
        analyze(db, {r['id'] for r in sample})
        audit(db, 'Sample inventory restored', 'Explicit sample reset; audit history retained.', p.email)
    db.commit()
    return result


@app.post('/api/scans')
def scan_inventory(db: DB, p: Member):
    writer_lock(db)
    result = analyze(db)
    audit(db, 'Analysis completed', f"{result['resources']} resources assessed; {result['findings']} findings. No cloud APIs called.", p.email)
    db.commit()
    return result


@app.post('/api/recommendations/{resource_id:path}/decision')
def recommendation_decision(resource_id: str, payload: DecisionInput, db: DB, p: Member):
    result = decide(db, resource_id, payload, p.email)
    db.commit()
    return result


@app.post('/api/explanations/{resource_id:path}')
def explain_resource(resource_id: str, db: DB, p: Member):
    org = org_of(db)
    rec, resource = db.get(Recommendation, (org, resource_id)), db.get(Resource, (org, resource_id))
    if not rec or not resource:
        raise HTTPException(404, 'Recommendation not found')
    if not configured():
        return {'source': 'rules', 'text': rec.finding['reason']}
    # External calls are opt-in via server environment. Limit fields sent to the LLM.
    d = resource.data
    evidence = {'cloud': d['provider'], 'environment': d['env'], 'p95_cpu_percent': d['cpu'], 'p95_memory_percent': d['memory'],
                'observation_days': d['days'], 'metric_coverage_percent': d['coverage'], 'business_critical': d['critical']}
    evidence.update(rec.finding)
    try:
        explanation = llm_complete([
            {'role': 'system', 'content': 'Explain the provided finding in plain English using only the supplied evidence. ' + GUARD + ' Include uncertainty.'},
            {'role': 'user', 'content': json.dumps(evidence)}], max_tokens=1200).get('content')
        if not isinstance(explanation, str) or not explanation.strip():
            raise AIError('AI returned an empty answer.')
    except AIError:
        raise HTTPException(502, 'AI provider unavailable. The deterministic finding remains valid.')
    return {'source': 'llm', 'text': explanation[:5000]}


@app.get('/api/reports/recommendations.csv')
def report(db: DB, p: Member):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['Resource', 'Provider', 'Environment', 'Owner', 'Finding', 'Action', 'Risk', 'Status', 'Estimated monthly savings USD', 'Mode'])
    def safe(value):
        text_value = str(value)
        return "'" + text_value if text_value.lstrip().startswith(('=', '+', '-', '@')) or text_value.startswith(('\t', '\r', '\n')) else text_value
    for row in workspace(db)['findings']:
        if row['kind'] != 'Healthy':
            writer.writerow([safe(row[k]) for k in ['name', 'provider', 'env', 'owner', 'kind', 'action', 'risk', 'status', 'saving']] + ['dry-run estimate'])
    return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="cloud-cost-recommendations.csv"'})
