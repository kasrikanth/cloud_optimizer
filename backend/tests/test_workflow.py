from urllib.parse import quote
from app.rules import evaluate


def seed(client, headers):
    response = client.post('/api/seed', json={'replace': False}, headers=headers)
    assert response.status_code == 200, response.text
    return client.get('/api/workspace', headers=headers).json()


def get_row(client, headers, resource_id='vm-checkout-stage'):
    data = client.get('/api/workspace', headers=headers).json()
    return next(r for r in data['findings'] if r['id'] == resource_id)


def decision(client, headers, row, action, reviewer='Test reviewer'):
    return client.post('/api/recommendations/' + quote(row['id'], safe='') + '/decision',
        headers=headers, json={'action': action, 'expected_version': row['version'], 'expected_generation': row['generation'], 'reviewer': reviewer})


def test_auth_boundaries(client, headers):
    assert client.get('/api/workspace').status_code == 401
    assert client.get('/api/workspace', headers={'Authorization': 'Bearer not-a-session'}).status_code == 401
    assert client.get('/api/workspace', headers=headers).status_code == 200
    assert client.get('/health').json()['execution_mode'] == 'dry-run'


def test_seed_and_server_findings(client, headers):
    data = seed(client, headers)
    assert len(data['resources']) == 12
    assert len([r for r in data['findings'] if r['kind'] != 'Healthy']) == 8
    assert sum(r['saving'] for r in data['findings']) == 1293
    assert client.post('/api/seed', json={}, headers=headers).status_code == 409
    # Reload from a separate HTTP request must retain database content.
    assert len(client.get('/api/workspace', headers=headers).json()['resources']) == 12


def test_decision_state_machine_and_optimistic_lock(client, headers):
    seed(client, headers)
    row = get_row(client, headers)
    assert decision(client, headers, row, 'simulate').status_code == 409
    assert decision(client, headers, row, 'approve', reviewer='').status_code == 422
    assert decision(client, headers, row, 'approve').status_code == 200
    assert decision(client, headers, row, 'simulate').status_code == 409
    latest = get_row(client, headers)
    assert latest['status'] == 'Approved'
    assert decision(client, headers, latest, 'simulate').json()['mode'] == 'dry-run'
    latest = get_row(client, headers)
    assert latest['status'] == 'Simulated'
    assert decision(client, headers, latest, 'simulate').status_code == 409
    assert decision(client, headers, latest, 'reopen').status_code == 200
    assert get_row(client, headers)['status'] == 'Pending'


def test_changed_input_invalidates_approval_but_scan_preserves_it(client, headers, sample):
    seed(client, headers)
    row = get_row(client, headers)
    assert decision(client, headers, row, 'approve').status_code == 200
    client.post('/api/scans', headers=headers)
    approved = get_row(client, headers)
    assert approved['status'] == 'Approved'
    changed = {**sample[0], 'cpu': 4}
    assert client.post('/api/inventory', headers=headers, json={'resources': [changed]}).status_code == 200
    updated = get_row(client, headers)
    assert updated['status'] == 'Pending'
    assert updated['version'] > approved['version']
    assert decision(client, headers, approved, 'simulate').status_code == 409


def test_invalid_inventory_is_atomic(client, headers, sample):
    seed(client, headers)
    bad = {**sample[0], 'cost': -10}
    assert client.post('/api/inventory', headers=headers, json={'resources': [bad], 'replace': True}).status_code == 422
    assert client.post('/api/inventory', headers=headers, json={'resources': [sample[0], sample[0]]}).status_code == 422
    assert len(client.get('/api/workspace', headers=headers).json()['resources']) == 12


def test_missing_telemetry_and_production_protection(sample):
    assert evaluate({**sample[0], 'memory': None})['saving'] == 0
    assert evaluate({**sample[0], 'days': 13})['saving'] == 0
    assert evaluate({**sample[0], 'coverage': 94})['saving'] == 0
    for changed in [{'env': 'Production'}, {'critical': True}]:
        finding = evaluate({**sample[0], **changed})
        assert finding['action'] != 'Stop VM'
        assert finding['risk'] == 'High'


def test_restore_preserves_audit_and_invalidates_old_versions(client, headers):
    seed(client, headers)
    row = get_row(client, headers)
    decision(client, headers, row, 'approve')
    approved = get_row(client, headers)
    old_logs = len(client.get('/api/workspace', headers=headers).json()['log'])
    assert client.post('/api/seed', headers=headers, json={'replace': True}).status_code == 200
    assert get_row(client, headers)['status'] == 'Pending'
    assert decision(client, headers, approved, 'simulate').status_code == 409
    assert len(client.get('/api/workspace', headers=headers).json()['log']) > old_logs


def test_csv_formula_escape_and_explanation_fallback(client, headers, sample):
    row = {**sample[0], 'name': '=HYPERLINK("http://bad.invalid")'}
    assert client.post('/api/inventory', headers=headers, json={'resources': [row]}).status_code == 200
    response = client.get('/api/reports/recommendations.csv', headers=headers)
    assert response.status_code == 200
    assert "'=HYPERLINK" in response.text
    explanation = client.post('/api/explanations/' + row['id'], headers=headers).json()
    assert explanation['source'] == 'rules'
    assert 'non-production' in explanation['text']


def test_slash_resource_id_decision_routing(client, headers, sample):
    row = {**sample[0], 'id': 'subscriptions/demo/vm-1'}
    client.post('/api/inventory', headers=headers, json={'resources': [row]})
    finding = get_row(client, headers, row['id'])
    assert decision(client, headers, finding, 'approve').status_code == 200


def test_deleted_and_reimported_resource_rejects_old_decision(client, headers, sample):
    client.post('/api/inventory', headers=headers, json={'resources': [sample[0]], 'replace': True})
    old = get_row(client, headers)
    client.post('/api/inventory', headers=headers, json={'resources': [sample[1]], 'replace': True})
    client.post('/api/inventory', headers=headers, json={'resources': [sample[0]], 'replace': True})
    new = get_row(client, headers)
    assert old['version'] == new['version']
    assert old['generation'] != new['generation']
    assert decision(client, headers, old, 'approve').status_code == 409
