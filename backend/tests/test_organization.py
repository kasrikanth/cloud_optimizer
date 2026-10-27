from tests.test_workflow import seed


def test_accounts_lifecycle_and_validation(client, headers, sample):
    body = {'name': 'Team GCP', 'provider': 'GCP', 'account_ref': 'proj-team-001', 'region': 'us-central1'}
    created = client.post('/api/accounts', headers=headers, json=body)
    assert created.status_code == 200, created.text
    assert client.post('/api/accounts', headers=headers, json=body).status_code == 409
    account_id = created.json()['id']
    gcp = {**sample[0], 'id': 'gce-1', 'provider': 'GCP', 'type': 'n2-standard-8', 'accountId': account_id}
    assert client.post('/api/inventory', headers=headers, json={'resources': [gcp]}).status_code == 200
    # Wrong provider for the account, and unknown account, are rejected before anything is written.
    assert client.post('/api/inventory', headers=headers, json={'resources': [{**gcp, 'provider': 'AWS'}]}).status_code == 422
    assert client.post('/api/inventory', headers=headers, json={'resources': [{**gcp, 'accountId': 'nope'}]}).status_code == 422
    rows = client.get('/api/accounts', headers=headers).json()['accounts']
    mine = next(a for a in rows if a['id'] == account_id)
    assert mine['resources'] == 1 and mine['monthlyCost'] == gcp['cost']
    assert client.delete('/api/accounts/' + account_id, headers=headers).json()['removedResources'] == 1
    assert client.delete('/api/accounts/' + account_id, headers=headers).status_code == 404
    assert all(r['id'] != 'gce-1' for r in client.get('/api/workspace', headers=headers).json()['resources'])


def test_multicloud_dashboard_matches_inventory(client, headers):
    seed(client, headers)
    data = client.get('/api/dashboard', headers=headers).json()
    assert data['totals']['resources'] == 12 and data['totals']['accounts'] == 4
    assert data['totals']['potentialSavings'] == 1293
    assert {p['provider'] for p in data['byProvider']} == {'AWS', 'Azure'}
    assert sum(p['monthlyCost'] for p in data['byProvider']) == data['totals']['monthlyCost']
    assert sum(a['resources'] for a in data['accounts']) == 12


def test_service_comparison_maps_inventory_types(client, headers):
    seed(client, headers)
    data = client.get('/api/comparison', headers=headers).json()
    assert len(data['classes']) >= 6 and data['resources']
    row = next(r for r in data['resources'] if r['id'] == 'i-analytics-dev')
    assert row['classId'] == 'gp-8-32' and row['cheapest']['provider'] == 'AWS'
    assert row['arm']['savingsPct'] > 0


def test_monitor_reports_telemetry_gaps_and_empty_accounts(client, headers):
    seed(client, headers)
    client.post('/api/accounts', headers=headers, json={'name': 'Empty AWS', 'provider': 'AWS', 'account_ref': '999988887777'})
    data = client.get('/api/monitor', headers=headers).json()
    titles = {(i['target'], i['title']) for i in data['issues']}
    assert ('etl-experimental', 'Telemetry incomplete') in titles
    assert ('Empty AWS', 'No data received') in titles
    assert data['status'] in ('Attention', 'Critical') and data['pipeline']['database'] == 'ok'
    assert any(a['state'] == 'Awaiting data' for a in data['accounts'])
    assert all(i['fix'] for i in data['issues'])
