from datetime import datetime, timedelta, timezone
import httpx
import pytest
from sqlalchemy import select
from app.collectors import AwsCollector, AzureCollector
from app.collectors.base import Collection, Collector, CollectorError
from app.models import CloudAccount, MetricSnapshot
from tests.test_workflow import decision, get_row, seed

AWS_ID = '123412341234'


def vm(**over):
    row = dict(id='i-0abc', name='sandbox-01', provider='AWS', region='ap-south-1', type='m5.xlarge', env='Development', owner='Platform',
               cost=140, targetCost=70, cpu=3, memory=9, network=0.2, days=30, coverage=99, hours=730, critical=False)
    return {**row, **over}


class Fake(Collector):
    mode = 'demo'

    def __init__(self, rows=None, error=None):
        self.rows, self.error = rows if rows is not None else [vm()], error

    def test(self, account, credentials):
        return 'ok'

    def collect(self, account, credentials):
        if self.error:
            raise self.error
        return Collection(resources=[{**r, 'accountId': account.id} for r in self.rows])


@pytest.fixture
def fake(monkeypatch):
    holder = {'collector': Fake()}
    monkeypatch.setattr('app.sync.get_collector', lambda mode: holder['collector'] if mode in ('demo', 'aws', 'azure') else None)
    return holder


def add_account(client, headers, mode='demo', provider='AWS', ref=AWS_ID, **extra):
    body = {'name': 'Test account', 'provider': provider, 'account_ref': ref, 'mode': mode, **extra}
    response = client.post('/api/accounts', headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def sync(client, headers, account_id):
    return client.post(f'/api/accounts/{account_id}/sync', headers=headers).json()


def test_demo_account_syncs_with_history_and_confidence(client, headers):
    created = add_account(client, headers, ref='555566667777')
    assert created['sync']['status'] == 'Success' and created['sync']['resources'] >= 5
    findings = client.get('/api/workspace', headers=headers).json()['findings']
    idle = next(f for f in findings if f['kind'] == 'Idle resource')
    assert idle['confidence']['level'] == 'High' and idle['confidence']['samples'] >= 7
    history = client.get('/api/resources/' + idle['id'] + '/history', headers=headers).json()['points']
    assert len(history) >= 14
    runs = client.get(f"/api/accounts/{created['id']}/syncs", headers=headers).json()['runs']
    assert runs and runs[0]['status'] == 'Success'


def test_routine_sync_keeps_approval_but_material_change_resets_it(client, headers, fake):
    account = add_account(client, headers)
    row = get_row(client, headers, 'i-0abc')
    assert decision(client, headers, row, 'approve').status_code == 200
    fake['collector'].rows = [vm(cpu=3.6, memory=10.2, network=0.3)]  # metric noise only
    assert sync(client, headers, account['id'])['status'] == 'Success'
    assert get_row(client, headers, 'i-0abc')['status'] == 'Approved'
    fake['collector'].rows = [vm(type='m5.2xlarge', cost=280, targetCost=140)]  # different instance: material
    sync(client, headers, account['id'])
    assert get_row(client, headers, 'i-0abc')['status'] == 'Pending'


def test_ledger_verifies_removed_and_resized_resources(client, headers, fake):
    account = add_account(client, headers)
    fake['collector'].rows = [vm(), vm(id='i-0def', name='resize-me', cpu=20, memory=30, env='Staging')]
    sync(client, headers, account['id'])
    for rid in ('i-0abc', 'i-0def'):
        row = get_row(client, headers, rid)
        assert decision(client, headers, row, 'approve').status_code == 200
        assert decision(client, headers, get_row(client, headers, rid), 'implement').status_code == 200
    assert decision(client, headers, get_row(client, headers, 'i-0abc'), 'reopen').status_code == 409
    waiting = client.get('/api/savings', headers=headers).json()
    assert waiting['counts']['awaiting'] == 2 and waiting['funnel']['verified'] == 0
    # i-0abc is stopped (gone); i-0def is replaced by a half-price size.
    fake['collector'].rows = [vm(id='i-0def', name='resize-me', type='m5.large', cost=70, targetCost=70, cpu=20, memory=30, env='Staging')]
    sync(client, headers, account['id'])
    ledger = client.get('/api/savings', headers=headers).json()
    by_name = {e['resource']: e for e in ledger['entries']}
    assert by_name['sandbox-01']['status'] == 'Verified' and by_name['sandbox-01']['verifiedSaving'] == 140
    assert by_name['resize-me']['status'] == 'Verified' and by_name['resize-me']['verifiedSaving'] == 70
    assert ledger['funnel']['verified'] == 210 and ledger['annualizedVerified'] == 2520


def test_sync_failure_is_recorded_redacted_and_surfaced(client, headers, fake):
    account = add_account(client, headers)
    fake['collector'].error = CollectorError('boom')
    result = sync(client, headers, account['id'])
    assert result['status'] == 'Failed'
    row = next(a for a in client.get('/api/accounts', headers=headers).json()['accounts'] if a['id'] == account['id'])
    assert row['lastSyncStatus'] == 'Failed' and row['lastSyncError'] == 'boom'
    issues = client.get('/api/monitor', headers=headers).json()['issues']
    assert any(i['title'] == 'Sync failed' and i['severity'] == 'critical' for i in issues)
    fake['collector'].error = None
    assert sync(client, headers, account['id'])['status'] == 'Success'


def test_import_accounts_cannot_sync_and_gcp_has_no_live_mode(client, headers):
    created = add_account(client, headers, mode='import', ref='444455556666')
    assert client.post(f"/api/accounts/{created['id']}/sync", headers=headers).status_code == 409
    body = {'name': 'GCP project', 'provider': 'GCP', 'account_ref': 'my-gcp-project', 'mode': 'aws'}
    assert client.post('/api/accounts', headers=headers, json=body).status_code == 422


def test_credentials_are_validated_encrypted_and_never_returned(client, headers, session_factory):
    creds = {'access_key_id': 'AKIAABCDEFGHIJKLMNOP', 'secret_access_key': 'S3cr3tS3cr3tS3cr3tS3cr3tS3cr3tS3cr3t0000', 'regions': 'ap-south-1, us-east-1'}
    bad = {'name': 'Prod AWS', 'provider': 'AWS', 'account_ref': 'not-a-number', 'mode': 'aws', 'credentials': creds}
    assert client.post('/api/accounts', headers=headers, json=bad).status_code == 422
    assert client.post('/api/accounts', headers=headers, json={**bad, 'account_ref': AWS_ID, 'credentials': {'access_key_id': 'AKIAABCDEFGHIJKLMNOP'}}).status_code == 422
    assert client.post('/api/accounts', headers=headers, json={**bad, 'account_ref': AWS_ID, 'mode': 'demo'}).status_code == 422
    ok = client.post('/api/accounts', headers=headers, json={**bad, 'account_ref': AWS_ID})
    assert ok.status_code == 200, ok.text
    with session_factory() as db:
        stored = db.scalar(select(CloudAccount).where(CloudAccount.id == ok.json()['id'])).credentials_enc
    assert stored and 'S3cr3t' not in stored and 'AKIA' not in stored
    listing = client.get('/api/accounts', headers=headers)
    assert 'S3cr3t' not in listing.text and 'AKIAABCDEFGHIJKLMNOP' not in listing.text
    assert next(a for a in listing.json()['accounts'] if a['id'] == ok.json()['id'])['hasCredentials'] is True


def test_account_edit_and_budget_alerts(client, headers, fake):
    account = add_account(client, headers)
    assert client.patch(f"/api/accounts/{account['id']}", headers=headers, json={'budget_usd': 100}).status_code == 200
    issues = client.get('/api/monitor', headers=headers).json()['issues']
    assert any(i['title'] == 'Over budget' and i['severity'] == 'critical' for i in issues)
    row = next(a for a in client.get('/api/accounts', headers=headers).json()['accounts'] if a['id'] == account['id'])
    assert row['budgetUsd'] == 100 and row['utilization'] == 140
    client.patch(f"/api/accounts/{account['id']}", headers=headers, json={'budget_usd': None})
    assert not any(i['title'] == 'Over budget' for i in client.get('/api/monitor', headers=headers).json()['issues'])


def test_anomaly_detection_flags_cpu_spike(client, headers, fake, session_factory):
    add_account(client, headers)
    with session_factory.begin() as db:
        now = datetime.now(timezone.utc)
        db.query(MetricSnapshot).delete()
        for i in range(10):
            db.add(MetricSnapshot(resource_id='i-0abc', captured_at=now - timedelta(days=10 - i), cpu=10, memory=20, network=1, cost=140))
        db.add(MetricSnapshot(resource_id='i-0abc', captured_at=now, cpu=75, memory=20, network=1, cost=140))
    issues = client.get('/api/monitor', headers=headers).json()['issues']
    assert any(i['title'] == 'Unusual CPU' and i['target'] == 'sandbox-01' for i in issues)


def test_organization_profile_and_members(client, headers):
    assert client.put('/api/organization', headers=headers, json={'name': 'Acme Cloud Team'}).json()['name'] == 'Acme Cloud Team'
    data = client.get('/api/organization', headers=headers).json()
    assert data['name'] == 'Acme Cloud Team' and data['members'][0]['email'] == 'admin@test.example'
    assert client.put('/api/organization', headers=headers, json={'name': 'x'}).status_code == 422


def test_ask_answers_from_data(client, headers):
    seed(client, headers)
    ask = lambda q: client.post('/api/ask', headers=headers, json={'question': q}).json()
    assert ask('How much can we save?')['topic'] == 'savings' and '$1,293' in ask('How much can we save?')['answer']
    assert ask('Which resources are idle?')['topic'] == 'idle'
    assert ask('What is wrong right now?')['topic'] == 'health'
    assert ask('Which cloud costs the most?')['topic'] == 'spend'
    assert ask('What has been saved so far?')['topic'] == 'impact'
    assert ask('blah blah')['topic'] == 'help'


# ---------------------------------------------------------------- collectors
class FakeEc2:
    def __init__(self, instances):
        self.instances = instances

    def get_paginator(self, name):
        assert name == 'describe_instances'
        outer = self
        return type('P', (), {'paginate': lambda self, **kw: iter([{'Reservations': [{'Instances': outer.instances}]}])})()


class FakeCloudWatch:
    def get_metric_data(self, **kw):
        results = []
        for query in kw['MetricDataQueries']:
            kind = query['Id'][0]
            values = {'c': [2.0] * 300, 'm': [], 'i': [1e6] * 300, 'o': [1e6] * 300}[kind]
            results.append({'Id': query['Id'], 'Values': values})
        return {'MetricDataResults': results}


def aws_factory(instances, account='123412341234'):
    def make(service, **kw):
        if service == 'ec2':
            return FakeEc2(instances)
        if service == 'cloudwatch':
            return FakeCloudWatch()
        return type('S', (), {'get_caller_identity': lambda self: {'Account': account, 'Arn': 'arn:aws:iam::x:user/y'}})()
    return make


def test_aws_collector_maps_instances_and_withholds_memory_without_agent():
    launch = datetime.now(timezone.utc) - timedelta(days=30)
    instances = [{'InstanceId': 'i-1', 'InstanceType': 'm5.xlarge', 'LaunchTime': launch, 'Tags': [{'Key': 'Name', 'Value': 'web'}, {'Key': 'Environment', 'Value': 'dev'}, {'Key': 'Owner', 'Value': 'Team A'}]},
                 {'InstanceId': 'i-2', 'InstanceType': 'z9.mega', 'LaunchTime': launch}]
    account = type('A', (), {'id': 'acct-1', 'account_ref': '123412341234'})()
    creds = {'access_key_id': 'AKIAABCDEFGHIJKLMNOP', 'secret_access_key': 'x' * 30, 'regions': ['ap-south-1']}
    collector = AwsCollector(client_factory=aws_factory(instances))
    result = collector.collect(account, creds)
    assert len(result.resources) == 1 and any('z9.mega' in w for w in result.warnings)
    row = result.resources[0]
    assert (row['name'], row['env'], row['owner'], row['type'], row['cost'], row['targetCost']) == ('web', 'Development', 'Team A', 'm5.xlarge', 140, 70)
    assert row['cpu'] == 2.0 and row['memory'] is None and row['days'] == 14 and row['coverage'] == 89.3
    assert collector.test(account, creds).startswith('Connected')
    with pytest.raises(CollectorError, match='belong to AWS account'):
        AwsCollector(client_factory=aws_factory(instances, account='999999999999')).test(account, creds)


def test_untagged_resources_default_to_production_so_they_are_never_suggested_for_stop():
    launch = datetime.now(timezone.utc) - timedelta(days=30)
    account = type('A', (), {'id': 'acct-1', 'account_ref': '123412341234'})()
    creds = {'access_key_id': 'AKIAABCDEFGHIJKLMNOP', 'secret_access_key': 'x' * 30, 'regions': ['ap-south-1']}
    row = AwsCollector(client_factory=aws_factory([{'InstanceId': 'i-1', 'InstanceType': 'm5.large', 'LaunchTime': launch}])).collect(account, creds).resources[0]
    assert row['env'] == 'Production' and row['owner'] == 'Unassigned'


def azure_transport(vm_size='Standard_D4s_v5', power='PowerState/running'):
    vm_id = '/subscriptions/aaaaaaaa-0000-4000-8000-000000000001/resourceGroups/rg-app/providers/Microsoft.Compute/virtualMachines/vm1'

    def handler(request: httpx.Request):
        url = str(request.url)
        if 'oauth2/v2.0/token' in url:
            return httpx.Response(200, json={'access_token': 'tok'})
        assert request.headers['authorization'] == 'Bearer tok'
        if url.endswith('api-version=2022-12-01'):
            return httpx.Response(200, json={'displayName': 'Prod sub'})
        if 'metrics' in url:
            hour = [{'average': 40.0, 'total': 1e6}] * 300
            return httpx.Response(200, json={'value': [
                {'name': {'value': 'Percentage CPU'}, 'timeseries': [{'data': hour}]},
                {'name': {'value': 'Available Memory Bytes'}, 'timeseries': [{'data': [{'average': 8 * 1024 ** 3}] * 300}]},
                {'name': {'value': 'Network In Total'}, 'timeseries': [{'data': hour}]},
                {'name': {'value': 'Network Out Total'}, 'timeseries': [{'data': hour}]}]})
        if 'statusOnly=true' in url:
            return httpx.Response(200, json={'value': [{'id': vm_id, 'properties': {'instanceView': {'statuses': [{'code': power}]}}}]})
        return httpx.Response(200, json={'value': [{'id': vm_id, 'name': 'vm1', 'location': 'centralindia', 'tags': {'env': 'prod', 'critical': 'true'},
                                                    'properties': {'hardwareProfile': {'vmSize': vm_size}, 'timeCreated': (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()}}]})
    return httpx.MockTransport(handler)


def test_azure_collector_reads_running_vms_and_derives_memory_percent():
    account = type('A', (), {'id': 'acct-2', 'account_ref': 'aaaaaaaa-0000-4000-8000-000000000001'})()
    creds = {'tenant_id': 'bbbbbbbb-0000-4000-8000-000000000002', 'client_id': 'cccccccc-0000-4000-8000-000000000003', 'client_secret': 'secret-value'}
    result = AzureCollector(transport=azure_transport()).collect(account, creds)
    row = result.resources[0]
    assert (row['type'], row['env'], row['critical'], row['cost'], row['targetCost']) == ('Standard_D4s_v5', 'Production', True, 140, 70)
    assert row['cpu'] == 40.0 and row['memory'] == 50.0 and row['id'] == 'aaaaaaaa-0000-4000-8000-000000000001/rg/rg-app/vm/vm1'
    assert AzureCollector(transport=azure_transport(power='PowerState/deallocated')).collect(account, creds).resources == []
    assert 'Prod sub' in AzureCollector(transport=azure_transport()).test(account, creds)


def test_demo_account_applies_implemented_changes_so_savings_verify_end_to_end(client, headers):
    created = add_account(client, headers, ref='555566667777')
    findings = client.get('/api/workspace', headers=headers).json()['findings']
    idle = next(f for f in findings if f['kind'] == 'Idle resource')
    resize = next(f for f in findings if f['kind'] == 'Oversized resource' and f['risk'] != 'High')
    for row in (idle, resize):
        assert decision(client, headers, row, 'approve').status_code == 200
        assert decision(client, headers, get_row(client, headers, row['id']), 'implement').status_code == 200
    assert client.get('/api/savings', headers=headers).json()['counts']['awaiting'] == 2
    assert sync(client, headers, created['id'])['status'] == 'Success'
    ledger = {e['resource']: e for e in client.get('/api/savings', headers=headers).json()['entries']}
    assert ledger[idle['name']]['status'] == 'Verified' and ledger[idle['name']]['verifiedSaving'] == idle['cost']
    assert ledger[resize['name']]['status'] == 'Verified' and ledger[resize['name']]['verifiedSaving'] == resize['saving']
    names = {f['name'] for f in client.get('/api/workspace', headers=headers).json()['findings']}
    assert idle['name'] not in names and resize['name'] in names
    # The change sticks: a later sync does not bring the stopped VM back.
    sync(client, headers, created['id'])
    assert idle['name'] not in {f['name'] for f in client.get('/api/workspace', headers=headers).json()['findings']}
