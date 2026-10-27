"""Emulator modes: static sandbox data behind fixed sandbox credentials, labelled as emulator, never as live."""
from collections import Counter
from sqlalchemy import select
from app import emulator_data
from app.collectors import AwsCollector, AzureCollector, EmulatorCollector, get_collector
from app.models import CloudAccount
from conftest import TestSession

AWS = emulator_data.CREDENTIALS['aws_emu']
AZURE = emulator_data.CREDENTIALS['azure_emu']
AWS_ACCOUNT = {'name': 'Northwind AWS', 'provider': 'AWS', 'account_ref': '000000000000', 'mode': 'aws_emu', 'credentials': AWS}
AZURE_ACCOUNT = {'name': 'Northwind Azure', 'provider': 'Azure', 'account_ref': '33333333-3333-4333-8333-333333333333', 'mode': 'azure_emu', 'credentials': AZURE}


def add(client, headers, body):
    response = client.post('/api/accounts', headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def kinds(client, headers, account_id):
    rows = client.get('/api/workspace', headers=headers).json()['findings']
    return Counter(r['kind'] for r in rows if r['accountId'] == account_id)


def test_aws_emulator_loads_the_startup_fleet_and_is_labelled_emulator(client, headers):
    account = add(client, headers, AWS_ACCOUNT)
    assert account['mode'] == 'aws_emu' and account['sync']['status'] == 'Success' and account['sync']['resources'] == 10
    row = next(a for a in client.get('/api/accounts', headers=headers).json()['accounts'] if a['id'] == account['id'])
    assert row['mode'] == 'aws_emu' and row['hasCredentials'] is True and row['resources'] == 10
    assert kinds(client, headers, account['id']) == {'Healthy': 3, 'Oversized resource': 3, 'Idle resource': 2, 'After-hours usage': 1, 'Review telemetry': 1}
    findings = client.get('/api/workspace', headers=headers).json()['findings']
    api = next(f for f in findings if f['name'] == 'api-prod-01')
    assert (api['kind'], api['action'], api['risk'], api['saving']) == ('Oversized resource', 'Resize VM', 'High', 62)  # production, so high risk
    assert api['confidence']['level'] == 'High' and api['confidence']['samples'] >= 7  # 14 days of history exist immediately
    assert next(f for f in findings if f['name'] == 'dev-sandbox-01')['action'] == 'Stop VM'
    assert next(f for f in findings if f['name'] == 'new-etl-02')['saving'] == 0  # six days of data: withheld, same rule as a live account


def test_azure_emulator_loads_the_startup_fleet(client, headers):
    account = add(client, headers, AZURE_ACCOUNT)
    assert account['sync']['resources'] == 9
    assert kinds(client, headers, account['id']) == {'Healthy': 3, 'Oversized resource': 2, 'Idle resource': 2, 'After-hours usage': 1, 'Review telemetry': 1}


def test_emulator_spend_and_inventory_appear_on_the_services_page_with_a_sandbox_notice(client, headers):
    add(client, headers, AWS_ACCOUNT)
    add(client, headers, AZURE_ACCOUNT)
    data = client.get('/api/cloud-services', headers=headers).json()
    assert len(data['months']) == 3 and data['spend']['total'][data['months'][1]] > 0
    assert any(r['service'] == 'Virtual Machines' for r in data['spend']['byService']) and any('Elastic Compute' in r['service'] for r in data['spend']['byService'])
    by = {r['service']: r for r in data['inventory']['byService']}
    assert by['EC2 Instance']['count'] == 10 and by['Virtual Machine']['count'] == 9
    assert by['EBS Volume']['notAttached'] == 2 and by['Elastic IP']['notAttached'] == 1 and by['Managed Disk']['notAttached'] == 1
    assert sorted(data['emulatorAccounts']) == ['Northwind AWS', 'Northwind Azure']


def test_only_the_published_sandbox_credentials_are_accepted(client, headers):
    wrong_secret = {**AWS_ACCOUNT, 'credentials': {**AWS, 'secret_access_key': AWS['secret_access_key'] + 'x'}}
    assert client.post('/api/accounts', headers=headers, json=wrong_secret).status_code == 422
    assert client.post('/api/accounts', headers=headers, json={**AWS_ACCOUNT, 'credentials': None}).status_code == 422
    assert client.post('/api/accounts', headers=headers, json={**AZURE_ACCOUNT, 'credentials': {**AZURE, 'client_secret': 'emulator-sandbox-secret-0002'}}).status_code == 422
    # A cloud cannot use the other cloud's emulator, and real-looking keys are not accepted as sandbox keys.
    assert client.post('/api/accounts', headers=headers, json={**AWS_ACCOUNT, 'provider': 'Azure', 'account_ref': AZURE_ACCOUNT['account_ref']}).status_code == 422
    real_looking = {**AWS_ACCOUNT, 'credentials': {'access_key_id': 'AKIAABCDEFGHIJKLMNOP', 'secret_access_key': 'x' * 30, 'regions': 'ap-south-1'}}
    assert client.post('/api/accounts', headers=headers, json=real_looking).status_code == 422
    assert client.get('/api/accounts', headers=headers).json()['accounts'] == []


def test_connection_test_and_rotation(client, headers):
    account = add(client, headers, AWS_ACCOUNT)
    result = client.post(f"/api/accounts/{account['id']}/test", headers=headers).json()
    assert result['ok'] is True and 'sandbox' in result['message'].lower()
    assert client.patch(f"/api/accounts/{account['id']}", headers=headers, json={'credentials': {**AWS, 'secret_access_key': 'nope' * 10}}).status_code == 422
    assert client.patch(f"/api/accounts/{account['id']}", headers=headers, json={'credentials': AWS, 'budget_usd': 1500}).status_code == 200


def test_credentials_are_stored_encrypted_even_though_they_are_public(client, headers):
    account = add(client, headers, AWS_ACCOUNT)
    with TestSession() as db:
        stored = db.scalar(select(CloudAccount.credentials_enc).where(CloudAccount.id == account['id']))
    assert stored and AWS['secret_access_key'] not in stored
    assert AWS['secret_access_key'] not in client.get('/api/accounts', headers=headers).text


def test_the_live_modes_are_not_affected(client, headers):
    # No special key unlocks sandbox data in a live mode: the live collectors are the real ones.
    assert isinstance(get_collector('aws'), AwsCollector) and isinstance(get_collector('azure'), AzureCollector)
    assert isinstance(get_collector('aws_emu'), EmulatorCollector) and isinstance(get_collector('azure_emu'), EmulatorCollector)
    assert get_collector('aws_emu') is not get_collector('aws_emu') and get_collector('aws_emu').mode == 'aws_emu'
    # A wrong-cloud request cannot reach the emulator through the API either.
    assert client.post('/api/accounts', headers=headers, json={**AWS_ACCOUNT, 'mode': 'azure_emu'}).status_code == 422


def test_emulator_account_runs_the_full_savings_loop(client, headers):
    account = add(client, headers, AWS_ACCOUNT)
    row = next(f for f in client.get('/api/workspace', headers=headers).json()['findings'] if f['name'] == 'dev-sandbox-01')
    post = lambda action, r, **kw: client.post(f"/api/recommendations/{row['id']}/decision", headers=headers,
                                              json={'action': action, 'expected_version': r['version'], 'expected_generation': r['generation'], **kw})
    assert post('approve', row, reviewer='Demo presenter').status_code == 200
    row = next(f for f in client.get('/api/workspace', headers=headers).json()['findings'] if f['id'] == row['id'])
    assert post('implement', row).status_code == 200
    # The emulator behaves like a cloud where the VM was stopped: the next sync no longer lists it, and the ledger verifies the saving.
    assert client.post(f"/api/accounts/{account['id']}/sync", headers=headers).json()['removed'] == 1
    savings = client.get('/api/savings', headers=headers).json()
    assert savings['counts']['verified'] == 1 and savings['funnel']['verified'] == 61.0


def test_two_organizations_can_each_use_the_emulator(client, headers, other_headers):
    mine = add(client, headers, AWS_ACCOUNT)
    theirs = add(client, other_headers, AWS_ACCOUNT)
    assert mine['id'] != theirs['id']
    mine_ids = {r['id'] for r in client.get('/api/workspace', headers=headers).json()['resources']}
    their_ids = {r['id'] for r in client.get('/api/workspace', headers=other_headers).json()['resources']}
    assert len(mine_ids) == len(their_ids) == 10 and not (mine_ids & their_ids)
