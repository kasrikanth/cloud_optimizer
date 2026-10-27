import json
import pytest
from app import llm
from app.config import get_settings


@pytest.fixture
def ai(monkeypatch):
    """Configure AI from 'the .env' and capture what would be sent to OpenAI. replies: list of message dicts, served in order."""
    settings = get_settings()
    monkeypatch.setattr(settings, 'llm_api_key', 'test-key')
    monkeypatch.setattr(settings, 'llm_model', 'test-model')
    monkeypatch.setattr(settings, 'llm_base_url', '')
    llm._recent.clear()
    box = {'sent': [], 'replies': []}

    def fake_post(body):
        box['sent'].append(body)
        reply = box['replies'].pop(0)
        if isinstance(reply, Exception):
            raise reply
        return {'choices': [{'message': reply}]}
    monkeypatch.setattr(llm, '_post', fake_post)
    return box


def js(**kw):
    return {'role': 'assistant', 'content': json.dumps(kw)}


def seeded(client, headers):
    assert client.post('/api/seed', headers=headers, json={'replace': False}).status_code == 200
    rows = client.get('/api/workspace', headers=headers).json()['findings']
    return next(r for r in rows if r['kind'] == 'Idle resource')


def test_everything_off_without_env_key(client, headers):
    row = seeded(client, headers)
    asked = client.post('/api/ask', headers=headers, json={'question': 'Which resources are idle?'}).json()
    assert asked['source'] == 'rules' and asked['items']
    for path in ['/api/ai/monitor-diagnosis', '/api/ai/report-narrative', '/api/ai/approval-assist/' + row['id'],
                 '/api/ai/anomaly/' + row['id']]:
        assert client.post(path, headers=headers).status_code == 503


def test_model_and_key_come_only_from_env(client, headers, ai):
    row = seeded(client, headers)
    ai['replies'] = [js(blast_radius='x', checks=[], rollback='y', approval_note='z')]
    client.post('/api/ai/approval-assist/' + row['id'], headers=headers, json={'model': 'attacker-model', 'api_key': 'evil'})
    assert ai['sent'][0]['model'] == 'test-model'
    assert 'attacker' not in json.dumps(ai['sent'][0])


def test_ask_routes_through_handlers_and_keeps_numbers(client, headers, ai):
    seeded(client, headers)
    ai['replies'] = [
        {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'idle', 'arguments': '{}'}}]},
        {'role': 'assistant', 'content': 'Two idle machines could be stopped.'}]
    result = client.post('/api/ask', headers=headers, json={'question': 'what can we switch off?'}).json()
    assert result['source'] == 'ai' and result['topic'] == 'idle'
    assert result['answer'] == 'Two idle machines could be stopped.'
    assert result['items'] and all('/mo' in i['value'] for i in result['items'])
    tool_message = next(m for m in ai['sent'][1]['messages'] if m['role'] == 'tool')
    assert 'Idle resource' in tool_message['content'] or 'idle' in tool_message['content'].lower()


def test_ask_ignores_unknown_tools_and_falls_back_on_failure(client, headers, ai):
    seeded(client, headers)
    ai['replies'] = [{'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'delete_everything', 'arguments': '{}'}}]}]
    unknown = client.post('/api/ask', headers=headers, json={'question': 'drop it'}).json()
    assert unknown['source'] == 'rules'  # an unlisted tool is never run; with no usable answer the rules respond
    ai['replies'] = [llm.AIError('AI provider unavailable.')]
    fallback = client.post('/api/ask', headers=headers, json={'question': 'Which resources are idle?'}).json()
    assert fallback['source'] == 'rules' and fallback['items'] and 'unavailable' in fallback['notice']


def test_monitor_diagnosis_filters_unknown_issue_ids(client, headers, ai, sample):
    stale = {**sample[0], 'memory': None}
    client.post('/api/inventory', headers=headers, json={'resources': [stale]})
    issues = client.get('/api/monitor', headers=headers).json()['issues']
    assert issues and all(i.get('resourceId') for i in issues if i['scope'] == 'resource')
    ai['replies'] = [js(summary='One cause.', causes=[{'title': 'Missing agent', 'explanation': 'No memory metrics.',
                                                       'issue_ids': [issues[0]['id'], 'made:up:id'], 'next_steps': ['Install the agent']}])]
    out = client.post('/api/ai/monitor-diagnosis', headers=headers).json()
    assert out['causes'][0]['issueIds'] == [issues[0]['id']]
    assert out['causes'][0]['nextSteps'] == ['Install the agent']


def test_report_narrative_and_provider_error(client, headers, ai):
    seeded(client, headers)
    ai['replies'] = [js(headline='Savings available', summary=['p1'], decisions=['d1'], risks=[])]
    out = client.post('/api/ai/report-narrative', headers=headers).json()
    assert out['headline'] == 'Savings available' and out['decisions'] == ['d1']
    ai['replies'] = [llm.AIError('AI provider unavailable.')]
    assert client.post('/api/ai/report-narrative', headers=headers).status_code == 502
    ai['replies'] = [{'role': 'assistant', 'content': 'not json'}]
    assert client.post('/api/ai/report-narrative', headers=headers).status_code == 502


def test_approval_assist_and_anomaly(client, headers, ai):
    row = seeded(client, headers)
    ai['replies'] = [js(blast_radius='Stops the VM.', checks=['Confirm owner'], rollback='Start it again.', approval_note='Approved after owner check.')]
    assist = client.post('/api/ai/approval-assist/' + row['id'], headers=headers).json()
    assert assist['checks'] == ['Confirm owner'] and assist['approvalNote']
    sent = json.dumps(ai['sent'][-1])
    assert 'test-key' not in sent and row['name'] in sent

    ai['replies'] = [js(summary='CPU rose.', likely_causes=[{'cause': 'Batch job', 'evidence': 'Spike at night', 'confidence': 'Certain'}], checks=['Check cron'])]
    anomaly = client.post('/api/ai/anomaly/' + row['id'], headers=headers).json()
    assert anomaly['causes'][0]['confidence'] == 'Low'  # unrecognized confidence is not passed through


def test_unknown_resource_and_auth(client, headers, ai):
    assert client.post('/api/ai/approval-assist/nope', headers=headers).status_code == 404
    assert client.post('/api/ai/approval-assist/nope').status_code == 401


def test_request_throttle(client, headers, ai, monkeypatch):
    seeded(client, headers)
    monkeypatch.setattr(llm, 'CALLS_PER_MINUTE', 1)
    ai['replies'] = [js(headline='h', summary=[], decisions=[], risks=[]), js(headline='h', summary=[], decisions=[], risks=[])]
    assert client.post('/api/ai/report-narrative', headers=headers).status_code == 200
    assert client.post('/api/ai/report-narrative', headers=headers).status_code == 502


def rising_account(client, headers, sample, session_factory):
    from datetime import timedelta
    from app.models import MetricSnapshot, utcnow
    account = client.post('/api/accounts', headers=headers, json={'name': 'Growth', 'provider': 'AWS', 'account_ref': '999988887777', 'budget_usd': 400}).json()
    row = {**sample[0], 'provider': 'AWS', 'accountId': account['id'], 'cost': 300}
    assert client.post('/api/inventory', headers=headers, json={'resources': [row], 'replace': True}).status_code == 200
    with session_factory() as db:
        for k in range(1, 10):  # nine earlier days, cost rising about $10 per day up to today's $300
            db.add(MetricSnapshot(resource_id=row['id'], account_id=account['id'], captured_at=utcnow() - timedelta(days=k), cpu=10, memory=20, network=1, cost=300 - 10 * k))
        db.commit()
    return account


def test_forecast_numbers_come_from_statistics(client, headers, sample, session_factory):
    from app.forecast import _fit
    slope, r2 = _fit([(0, 100), (1, 110), (2, 120), (3, 130)])
    assert round(slope, 6) == 10 and round(r2, 6) == 1
    account = rising_account(client, headers, sample, session_factory)
    f = client.get('/api/forecast', headers=headers).json()
    assert f['fleet']['sufficient'] and f['fleet']['projected'] > f['fleet']['current']
    row = next(a for a in f['accounts'] if a['id'] == account['id'])
    assert row['projected'] > 400 and row['budgetStatus'] == 'Likely to exceed'
    assert 8 <= row['daysToBudget'] <= 12


def test_forecast_without_history_is_marked_insufficient(client, headers):
    f = client.get('/api/forecast', headers=headers).json()
    assert f['fleet']['sufficient'] is False and f['accounts'] == []


def test_forecast_narrative_explains_but_does_not_compute(client, headers, sample, session_factory, ai):
    account = rising_account(client, headers, sample, session_factory)
    ai['replies'] = [js(summary='Spend is rising.', budget_risks=['Growth will pass its budget.'], actions=['Review pending savings.'], caveats=['Short history.'])]
    out = client.post('/api/ai/forecast', headers=headers).json()
    assert out['source'] == 'ai' and out['budgetRisks'] == ['Growth will pass its budget.']
    sent = json.loads(ai['sent'][0]['messages'][1]['content'])
    assert next(a for a in sent['forecast']['accounts'] if a['id'] == account['id'])['budgetStatus'] == 'Likely to exceed'
    assert 'never produce' in ai['sent'][0]['messages'][0]['content']


def test_forecast_narrative_skips_the_model_without_history(client, headers, ai):
    out = client.post('/api/ai/forecast', headers=headers).json()
    assert 'not enough history' in out['summary'] and ai['sent'] == []
