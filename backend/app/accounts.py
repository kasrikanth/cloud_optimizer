"""Cloud accounts. Credentials, when provided for a live collector, are encrypted at rest and never returned."""
import re
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from . import emulator_data
from .collectors import EMULATOR_MODES, MODES_BY_PROVIDER
from .models import CloudAccount, Recommendation, Resource
from . import cloud_services
from .tenant import org_of
from .vault import seal

MAX_ACCOUNTS = 50
UUID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')

# The sample inventory refers to accounts by these aliases. Each organization gets its own real account (own ID) the first
# time the sample is loaded, and the aliases are rewritten to those IDs.
SAMPLE_ACCOUNTS = {
    'acct-azure-prod': dict(name='Azure · Production', provider='Azure', account_ref='a1b2c3d4-1111-4222-8333-000000000001', region='Central India'),
    'acct-azure-nonprod': dict(name='Azure · Non-production', provider='Azure', account_ref='a1b2c3d4-1111-4222-8333-000000000002', region='Central India'),
    'acct-aws-prod': dict(name='AWS · Production', provider='AWS', account_ref='111122223333', region='ap-south-1'),
    'acct-aws-dev': dict(name='AWS · Development', provider='AWS', account_ref='444455556666', region='ap-south-1'),
}
OPEN = ('Dismissed', 'Simulated', 'Implemented')


def get_account(db: Session, account_id: str) -> CloudAccount:
    """The account if it belongs to the signed-in organization. Another organization's account is reported as not found."""
    account = db.get(CloudAccount, account_id)
    if not account or account.org_id != org_of(db):
        raise HTTPException(404, 'Cloud account not found')
    return account


def ensure_accounts(db: Session, resources: list[dict], actor: str):
    """Validate every accountId referenced by incoming resources against this organization's accounts.
    Sample aliases are resolved to (or created as) this organization's own sample accounts; resources are updated in place."""
    org = org_of(db)
    wanted = {r['accountId'] for r in resources if r.get('accountId')}
    if not wanted:
        return
    mine = {a.id: a for a in db.scalars(select(CloudAccount).where(CloudAccount.org_id == org)).all()}
    resolved = {}
    for ref in wanted:
        if ref in SAMPLE_ACCOUNTS:
            sample = SAMPLE_ACCOUNTS[ref]
            found = next((a for a in mine.values() if a.provider == sample['provider'] and a.account_ref == sample['account_ref']), None)
            if found is None:
                found = CloudAccount(created_by=actor, mode='import', **sample)
                db.add(found)
                db.flush()
                mine[found.id] = found
            resolved[ref] = found.id
        elif ref in mine:
            resolved[ref] = ref
        else:
            raise HTTPException(422, f'Unknown cloud account "{ref}". Add it under Cloud accounts first.')
    for r in resources:
        if not r.get('accountId'):
            continue
        account = mine[resolved[r['accountId']]]
        if r['provider'] != account.provider:
            raise HTTPException(422, f'Resource {r["id"]} is {r["provider"]} but account "{r["accountId"]}" is {account.provider}.')
        r['accountId'] = account.id


def validate_credentials(mode: str, provider: str, account_ref: str, creds: dict | None) -> dict | None:
    if mode not in MODES_BY_PROVIDER[provider]:
        raise HTTPException(422, f'{provider} accounts support: {", ".join(MODES_BY_PROVIDER[provider])}.')
    if mode in ('demo', 'import'):
        if creds:
            raise HTTPException(422, f'{mode} accounts do not take credentials.')
        return None
    creds = creds or {}
    if mode in EMULATOR_MODES:
        # Same fields and formats as the live mode, but only the published sandbox credentials are accepted.
        checked = validate_credentials('aws' if mode == 'aws_emu' else 'azure', provider, account_ref, creds)
        expected = emulator_data.CREDENTIALS[mode]
        if any(checked[k] != v for k, v in expected.items() if k != 'regions'):
            raise HTTPException(422, f'These are not the sandbox credentials for the {provider} Emulator. Use the credentials shown in the form.')
        return checked
    if mode == 'aws':
        if not re.fullmatch(r'\d{12}', account_ref):
            raise HTTPException(422, 'A live AWS account needs its 12-digit account ID.')
        unknown = set(creds) - {'access_key_id', 'secret_access_key', 'regions'}
        if unknown or not {'access_key_id', 'secret_access_key', 'regions'} <= set(creds):
            raise HTTPException(422, 'AWS needs access_key_id, secret_access_key and regions.')
        regions = [x.strip() for x in str(creds['regions']).split(',') if x.strip()]
        if not regions or len(regions) > 6 or not all(re.fullmatch(r'[a-z]{2}(-[a-z]+)+-\d', x) for x in regions):
            raise HTTPException(422, 'Regions must be a comma-separated list such as ap-south-1,us-east-1 (max 6).')
        if not re.fullmatch(r'(AKIA|ASIA)[A-Z0-9]{12,}', creds['access_key_id']) or len(creds['secret_access_key']) < 20:
            raise HTTPException(422, 'The AWS access key ID or secret looks invalid.')
        return {'access_key_id': creds['access_key_id'], 'secret_access_key': creds['secret_access_key'], 'regions': regions}
    if not UUID.match(account_ref):
        raise HTTPException(422, 'A live Azure account needs its subscription ID (a UUID) as the identifier.')
    if set(creds) != {'tenant_id', 'client_id', 'client_secret'}:
        raise HTTPException(422, 'Azure needs tenant_id, client_id and client_secret.')
    if not UUID.match(creds['tenant_id']) or not UUID.match(creds['client_id']) or len(creds['client_secret']) < 8:
        raise HTTPException(422, 'The Azure tenant ID, client ID or secret looks invalid.')
    return dict(creds)


def create_account(db: Session, payload, actor: str) -> CloudAccount:
    org = org_of(db)
    if db.scalar(select(CloudAccount.id).where(CloudAccount.org_id == org, CloudAccount.provider == payload.provider,
                                                CloudAccount.account_ref == payload.account_ref)):
        raise HTTPException(409, 'This account is already connected.')
    if len(db.scalars(select(CloudAccount.id).where(CloudAccount.org_id == org)).all()) >= MAX_ACCOUNTS:
        raise HTTPException(409, f'Account limit reached ({MAX_ACCOUNTS}).')
    creds = validate_credentials(payload.mode, payload.provider, payload.account_ref, payload.credentials)
    account = CloudAccount(name=payload.name, provider=payload.provider, account_ref=payload.account_ref, region=payload.region,
                           created_by=actor, mode=payload.mode, budget_usd=payload.budget_usd,
                           credentials_enc=seal(creds) if creds else None)
    db.add(account)
    db.flush()
    return account


def update_account(db: Session, account_id: str, payload) -> CloudAccount:
    account = get_account(db, account_id)
    sent = payload.model_fields_set
    if 'name' in sent and payload.name:
        account.name = payload.name
    if 'budget_usd' in sent:
        account.budget_usd = payload.budget_usd
    if 'credentials' in sent and payload.credentials:
        creds = validate_credentials(account.mode, account.provider, account.account_ref, payload.credentials)
        account.credentials_enc = seal(creds) if creds else None
    db.flush()
    return account


def remove_account(db: Session, account_id: str) -> int:
    account = get_account(db, account_id)
    org = account.org_id
    ids = [r.id for r in db.scalars(select(Resource).where(Resource.org_id == org)).all() if r.data.get('accountId') == account_id]
    if ids:
        db.execute(delete(Recommendation).where(Recommendation.org_id == org, Recommendation.resource_id.in_(ids)))
        db.execute(delete(Resource).where(Resource.org_id == org, Resource.id.in_(ids)))
    cloud_services.remove_for_account(db, account_id)
    db.delete(account)
    db.flush()
    return len(ids)


def account_rows(db: Session, findings: list[dict]) -> list[dict]:
    """Accounts with live totals. Resources without an account are reported as a separate row."""
    accounts = db.scalars(select(CloudAccount).where(CloudAccount.org_id == org_of(db)).order_by(CloudAccount.provider, CloudAccount.name)).all()
    rows = []
    for a in accounts:
        mine = [f for f in findings if f.get('accountId') == a.id]
        row = _row(a.id, a.name, a.provider, a.account_ref, a.region, a.created_by, a.created_at.isoformat(), mine)
        row.update(mode=a.mode, budgetUsd=a.budget_usd, hasCredentials=bool(a.credentials_enc),
                   utilization=round(row['monthlyCost'] / a.budget_usd * 100) if a.budget_usd else None,
                   lastSyncAt=a.last_sync_at.isoformat() if a.last_sync_at else None,
                   lastSyncStatus=a.last_sync_status, lastSyncError=a.last_sync_error)
        rows.append(row)
    loose = [f for f in findings if not f.get('accountId')]
    if loose:
        rows.append(dict(_row(None, 'Unassigned resources', None, '', '', '', None, loose), mode=None, budgetUsd=None,
                         hasCredentials=False, utilization=None, lastSyncAt=None, lastSyncStatus=None, lastSyncError=None))
    return rows


def _row(id_, name, provider, ref, region, by, created, mine):
    open_ = [f for f in mine if f['status'] not in OPEN]
    return {'id': id_, 'name': name, 'provider': provider, 'accountRef': ref, 'region': region, 'createdBy': by,
            'createdAt': created, 'resources': len(mine), 'monthlyCost': sum(f['cost'] for f in mine),
            'potentialSavings': sum(f['saving'] for f in open_),
            'openRecommendations': len([f for f in open_ if f['kind'] != 'Healthy'])}
