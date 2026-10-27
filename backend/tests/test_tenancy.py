"""Multiple organizations: sign-up, password login, members, and strict data isolation between organizations."""
from datetime import timezone
from urllib.parse import quote
import pytest
from sqlalchemy import select
from app import sync
from app.models import AuditEvent, CloudAccount, Organization, SyncRun, User
from conftest import PASSWORD, TestSession, bearer, signup
from tests.test_platform import Fake
from tests.test_workflow import decision, get_row, seed


# ------------------------------------------------------------ sign-up / login
def test_signup_creates_organization_and_admin(client):
    body = signup(client, 'Acme Corp', 'Owner@Acme.example')
    assert body['user'] == {'email': 'owner@acme.example', 'name': '', 'role': 'admin'}
    assert body['organization']['name'] == 'Acme Corp'
    me = client.get('/api/auth/me', headers=bearer(body)).json()
    assert me['email'] == 'owner@acme.example' and me['role'] == 'admin' and me['organization']['id'] == body['organization']['id']
    assert client.get('/api/workspace', headers=bearer(body)).status_code == 200


def test_signup_validation_and_uniqueness(client):
    signup(client, 'Acme Corp', 'owner@acme.example')
    post = lambda **kw: client.post('/api/auth/signup', json={'organization': 'Beta', 'email': 'b@beta.example', 'password': PASSWORD, **kw})
    assert post(email='not-an-email').status_code == 422
    assert post(password='short').status_code == 422
    assert post(organization='x').status_code == 422
    assert post(organization='acme corp').status_code == 409  # organization names are unique, case-insensitively
    assert post(email='OWNER@acme.example').status_code == 409  # one account per email
    assert post().status_code == 200


def test_login_and_logout(client):
    signup(client, 'Acme Corp', 'owner@acme.example')
    login = lambda email='owner@acme.example', password=PASSWORD: client.post('/api/auth/login', json={'email': email, 'password': password})
    assert login(password='wrong-password').status_code == 401
    assert login(email='nobody@acme.example').status_code == 401
    ok = login(email='Owner@Acme.example')
    assert ok.status_code == 200 and ok.json()['organization']['name'] == 'Acme Corp'
    headers = bearer(ok.json())
    assert client.get('/api/workspace', headers=headers).status_code == 200
    assert client.post('/api/auth/logout', headers=headers).status_code == 200
    assert client.get('/api/workspace', headers=headers).status_code == 401


def test_login_lockout_after_repeated_failures(client):
    signup(client, 'Acme Corp', 'owner@acme.example')
    for _ in range(5):
        assert client.post('/api/auth/login', json={'email': 'owner@acme.example', 'password': 'bad-password'}).status_code == 401
    assert client.post('/api/auth/login', json={'email': 'owner@acme.example', 'password': PASSWORD}).status_code == 429


def test_passwords_are_hashed_and_old_otp_endpoints_are_gone(client):
    signup(client, 'Acme Corp', 'owner@acme.example')
    with TestSession() as db:
        stored = db.scalar(select(User.password_hash))
    assert stored.startswith('scrypt$') and PASSWORD not in stored
    assert client.post('/api/auth/verify', json={'email': 'owner@acme.example', 'otp': '123456'}).status_code == 404
    assert client.post('/api/integrations/boomi/inventory', json={}).status_code == 404


def test_actions_are_attributed_to_the_signed_in_member(client, headers, sample):
    assert client.post('/api/inventory', headers=headers, json={'resources': [sample[0]]}).status_code == 200
    log = client.get('/api/workspace', headers=headers).json()['log']
    assert any(e['actor'] == 'admin@test.example' and e['title'] == 'Inventory imported' for e in log)


# -------------------------------------------------------------------- members
def test_admin_manages_members_and_members_share_the_organization(client, headers):
    seed(client, headers)
    created = client.post('/api/members', headers=headers, json={'email': 'dev@test.example', 'password': PASSWORD, 'name': 'Dev', 'role': 'member'})
    assert created.status_code == 200, created.text
    assert client.post('/api/members', headers=headers, json={'email': 'dev@test.example', 'password': PASSWORD}).status_code == 409
    member = bearer(client.post('/api/auth/login', json={'email': 'dev@test.example', 'password': PASSWORD}).json())
    assert len(client.get('/api/workspace', headers=member).json()['resources']) == 12  # same organization, same data
    assert len(client.get('/api/members', headers=member).json()['members']) == 2
    # A member cannot manage people or rename the organization.
    assert client.post('/api/members', headers=member, json={'email': 'x@test.example', 'password': PASSWORD}).status_code == 403
    assert client.put('/api/organization', headers=member, json={'name': 'Hijacked'}).status_code == 403
    assert client.delete('/api/members/' + created.json()['id'], headers=member).status_code == 403
    # Removing a member ends their access straight away.
    assert client.delete('/api/members/' + created.json()['id'], headers=headers).status_code == 200
    assert client.get('/api/workspace', headers=member).status_code == 401
    assert client.post('/api/auth/login', json={'email': 'dev@test.example', 'password': PASSWORD}).status_code == 401


def test_cannot_remove_yourself_or_the_last_admin(client, headers, session):
    me = client.get('/api/members', headers=headers).json()['members'][0]['id']
    assert client.delete('/api/members/' + me, headers=headers).status_code == 409
    second = client.post('/api/members', headers=headers, json={'email': 'two@test.example', 'password': PASSWORD, 'role': 'admin'}).json()
    second_headers = bearer(client.post('/api/auth/login', json={'email': 'two@test.example', 'password': PASSWORD}).json())
    assert client.delete('/api/members/' + me, headers=second_headers).status_code == 200  # another admin remains
    assert client.delete('/api/members/' + second['id'], headers=second_headers).status_code == 409


def test_cannot_manage_another_organizations_members(client, headers, other_headers):
    theirs = client.get('/api/members', headers=other_headers).json()['members'][0]['id']
    assert client.delete('/api/members/' + theirs, headers=headers).status_code == 404


def test_signup_can_claim_an_organization_that_has_no_users(client):
    with TestSession.begin() as db:  # what the 0004 migration leaves behind for pre-existing single-organization data
        db.add(Organization(id='legacy-org', name='Legacy Co', updated_by='migration'))
    body = signup(client, 'Legacy Co', 'first@legacy.example')
    assert body['organization']['id'] == 'legacy-org' and body['user']['role'] == 'admin'
    assert client.post('/api/auth/signup', json={'organization': 'Legacy Co', 'email': 'late@legacy.example', 'password': PASSWORD}).status_code == 409


# ------------------------------------------------------------------ isolation
def test_each_organization_sees_only_its_own_data(client, headers, other_headers):
    seed(client, headers)
    client.post('/api/accounts', headers=headers, json={'name': 'A demo', 'provider': 'AWS', 'account_ref': '111122223333', 'mode': 'demo'})
    for path in ['/api/workspace', '/api/dashboard', '/api/accounts', '/api/savings', '/api/monitor', '/api/comparison', '/api/forecast', '/api/organization']:
        assert client.get(path, headers=headers).status_code == 200, path
    other = {p: client.get(p, headers=other_headers).json() for p in ['/api/workspace', '/api/dashboard', '/api/accounts', '/api/savings', '/api/comparison']}
    assert other['/api/workspace']['resources'] == [] and other['/api/workspace']['findings'] == []
    assert other['/api/accounts']['accounts'] == []
    assert other['/api/dashboard']['totals']['resources'] == 0 and other['/api/dashboard']['totals']['accounts'] == 0
    assert other['/api/savings']['entries'] == [] and other['/api/comparison']['resources'] == []
    # Audit history is per organization too: the other org only sees its own sign-up.
    assert all('Organization created' == e['title'] for e in other['/api/workspace']['log'])
    assert client.get('/api/reports/recommendations.csv', headers=other_headers).text.count('\n') <= 1
    assert client.get('/api/organization', headers=other_headers).json()['name'] == 'Other Org'
    assert [m['email'] for m in client.get('/api/members', headers=other_headers).json()['members']] == ['admin@other.example']


def test_organizations_can_hold_the_same_resource_ids_and_decide_independently(client, headers, other_headers):
    seed(client, headers)
    seed(client, other_headers)  # identical sample ids in both organizations
    mine, theirs = get_row(client, headers), get_row(client, other_headers)
    assert mine['id'] == theirs['id'] and mine['generation'] != theirs['generation']
    assert decision(client, headers, mine, 'approve').status_code == 200
    assert get_row(client, headers)['status'] == 'Approved'
    assert get_row(client, other_headers)['status'] == 'Pending'
    # A decision can't be replayed across organizations either: wrong generation.
    assert decision(client, other_headers, mine, 'approve').status_code == 409
    # Replacing one organization's inventory leaves the other untouched.
    assert client.post('/api/inventory', headers=other_headers, json={'resources': [], 'replace': True}).status_code == 422
    assert len(client.get('/api/workspace', headers=headers).json()['resources']) == 12


def test_cross_organization_access_by_id_is_not_found(client, headers, other_headers):
    seed(client, headers)
    account = client.post('/api/accounts', headers=headers, json={'name': 'Acct A', 'provider': 'AWS', 'account_ref': '999988887777', 'mode': 'import'}).json()
    rid = quote(get_row(client, headers)['id'], safe='')
    aid = account['id']
    assert client.patch(f'/api/accounts/{aid}', headers=other_headers, json={'name': 'Renamed'}).status_code == 404
    assert client.post(f'/api/accounts/{aid}/test', headers=other_headers).status_code == 404
    assert client.post(f'/api/accounts/{aid}/sync', headers=other_headers).status_code == 404
    assert client.get(f'/api/accounts/{aid}/syncs', headers=other_headers).status_code == 404
    assert client.delete(f'/api/accounts/{aid}', headers=other_headers).status_code == 404
    assert client.get(f'/api/resources/{rid}/history', headers=other_headers).json() == {'points': []}
    assert client.post(f'/api/explanations/{rid}', headers=other_headers).status_code == 404
    assert client.post(f'/api/recommendations/{rid}/decision', headers=other_headers,
                       json={'action': 'dismiss', 'expected_version': 1, 'expected_generation': 'x' * 36}).status_code == 404
    # Importing resources into another organization's account is rejected.
    row = {**get_row(client, headers), 'accountId': aid, 'provider': 'AWS'}
    resource = {k: row[k] for k in ['id', 'name', 'provider', 'accountId', 'region', 'type', 'env', 'owner', 'cost', 'targetCost', 'cpu', 'memory', 'network', 'days', 'coverage', 'hours', 'critical']}
    assert client.post('/api/inventory', headers=other_headers, json={'resources': [resource]}).status_code == 422
    # Nothing of the owner's changed.
    assert next(a for a in client.get('/api/accounts', headers=headers).json()['accounts'] if a['id'] == aid)['name'] == 'Acct A'


def test_each_organization_has_its_own_cloud_provider_details(client, headers, other_headers):
    body = {'name': 'Prod', 'provider': 'AWS', 'account_ref': '111122223333', 'mode': 'aws',
            'credentials': {'access_key_id': 'AKIAABCDEFGHIJKLMNOP', 'secret_access_key': 'S3cr3tS3cr3tS3cr3tS3cr3tS3cr3tS3cr3t0000', 'regions': 'ap-south-1'}}
    mine = client.post('/api/accounts', headers=headers, json=body)
    theirs = client.post('/api/accounts', headers=other_headers, json={**body, 'name': 'Their prod', 'mode': 'import', 'credentials': None})
    assert mine.status_code == 200 and theirs.status_code == 200  # the same AWS account id can be connected by both
    assert mine.json()['id'] != theirs.json()['id']
    mine_rows = client.get('/api/accounts', headers=headers).json()['accounts']
    their_rows = client.get('/api/accounts', headers=other_headers).json()['accounts']
    assert [(a['name'], a['hasCredentials']) for a in mine_rows] == [('Prod', True)]
    assert [(a['name'], a['hasCredentials']) for a in their_rows] == [('Their prod', False)]
    # Still unique inside one organization.
    assert client.post('/api/accounts', headers=headers, json=body).status_code == 409


def test_sample_accounts_are_created_per_organization(client, headers, other_headers):
    seed(client, headers)
    seed(client, other_headers)
    mine = {a['id'] for a in client.get('/api/accounts', headers=headers).json()['accounts'] if a['id']}
    theirs = {a['id'] for a in client.get('/api/accounts', headers=other_headers).json()['accounts'] if a['id']}
    assert len(mine) == len(theirs) == 4 and not (mine & theirs)
    resources = client.get('/api/workspace', headers=headers).json()['resources']
    assert {r['accountId'] for r in resources} <= mine


def test_scheduled_sync_runs_each_account_inside_its_own_organization(client, headers, other_headers, monkeypatch):
    monkeypatch.setattr('app.sync.get_collector', lambda mode: Fake() if mode == 'demo' else None)
    monkeypatch.setattr(sync, 'SessionLocal', TestSession)
    a = client.post('/api/accounts', headers=headers, json={'name': 'Acct A', 'provider': 'AWS', 'account_ref': '111122223333', 'mode': 'demo'}).json()
    b = client.post('/api/accounts', headers=other_headers, json={'name': 'Acct B', 'provider': 'AWS', 'account_ref': '444455556666', 'mode': 'demo'}).json()
    with TestSession.begin() as db:
        for account in db.scalars(select(CloudAccount)):
            account.last_sync_at = None
    assert sync.sync_due() == 2
    with TestSession() as db:
        runs = db.scalars(select(SyncRun)).all()
        orgs = {c.id: c.org_id for c in db.scalars(select(CloudAccount))}
        assert len(runs) == 4 and all(r.org_id == orgs[r.account_id] for r in runs)
        assert orgs[a['id']] != orgs[b['id']]
    for h, name in [(headers, 'sandbox-01'), (other_headers, 'sandbox-01')]:
        assert [r['name'] for r in client.get('/api/workspace', headers=h).json()['resources']] == [name]


def test_rows_cannot_be_written_without_an_organization(client):
    from app.tenant import bind
    with TestSession() as db:
        db.add(AuditEvent(title='x', detail='y', actor='z'))
        with pytest.raises(RuntimeError):
            db.flush()
    with TestSession() as db:
        bind(db, 'some-org')
        event = AuditEvent(title='x', detail='y', actor='z')
        db.add(event)
        db.flush()
        assert event.org_id == 'some-org'
        db.rollback()
