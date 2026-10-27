"""AI features. The rules, ledger and monitor stay the source of truth for every number and every status.
The model only routes questions, explains evidence and drafts text. It has no write access and no tool that changes data."""
import json
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from . import ask as ask_module
from .accounts import OPEN
from .forecast import forecast
from .history import anomalies, confidence, resource_history
from .insights import dashboard, monitor
from .llm import AIError, GUARD, NOT_CONFIGURED, complete, configured, generate_json
from .models import AuditEvent, CloudAccount, Recommendation, Resource, SavingsEntry, SyncRun
from .services import workspace
from .tenant import org_of

TOPIC_HELP = {
    'savings': 'Open savings recommendations and the biggest opportunities.',
    'idle': 'Idle resources that could be stopped.',
    'oversized': 'Oversized resources that could be resized.',
    'spend': 'Monthly spend, by cloud and by most expensive resources.',
    'health': 'Current health issues, stale data, failed syncs and telemetry problems.',
    'compare': 'Price comparison across AWS, Azure and GCP, and Arm options.',
    'budget': 'Account budgets and which accounts are over budget.',
    'impact': 'Verified savings so far and the savings pipeline.',
    'approval': 'Recommendations waiting for review or approval.',
    'risk': 'High-risk recommendations on production or critical workloads.',
    'accounts': 'Connected cloud accounts.',
}
TOOLS = [{'type': 'function', 'function': {'name': name, 'description': text,
                                           'parameters': {'type': 'object', 'properties': {}, 'additionalProperties': False}}}
         for name, text in TOPIC_HELP.items()]


# ------------------------------------------------------------------ helpers
def require():
    if not configured():
        raise HTTPException(503, NOT_CONFIGURED)


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except AIError as exc:
        raise HTTPException(502, str(exc)) from None


def _s(value, limit=1200) -> str:
    return str(value or '').strip()[:limit]


def _list(value, limit=8, size=400) -> list[str]:
    return [_s(x, size) for x in value[:limit] if _s(x, size)] if isinstance(value, list) else []


def _target(db: Session, resource_id: str):
    org = org_of(db)
    rec, res = db.get(Recommendation, (org, resource_id)), db.get(Resource, (org, resource_id))
    if not rec or not res:
        raise HTTPException(404, 'Recommendation not found')
    return rec, res


def _context(db: Session, rec: Recommendation, res: Resource) -> dict:
    """Evidence for one resource. Only inventory, rule output and metric history: no credentials, no tokens."""
    points = resource_history(db, res.id, 14)
    account = db.get(CloudAccount, res.data['accountId']) if res.data.get('accountId') else None
    if account and account.org_id != org_of(db):
        account = None
    finding = {k: rec.finding[k] for k in ('kind', 'action', 'saving', 'risk', 'reason')}
    if rec.finding['saving'] > 0:
        finding['confidence'] = confidence(res.data, points, rec.finding['kind'])
    return {'resource': res.data, 'recommendation': {**finding, 'status': rec.status, 'reviewer': rec.reviewer},
            'account': {'name': account.name, 'provider': account.provider, 'mode': account.mode, 'budgetUsd': account.budget_usd} if account else None,
            'recentReadings': points}


# ---------------------------------------------------- 1. Ask Stratus (router)
def ask(db: Session, question: str) -> dict:
    """The model picks which existing topic handlers to call and phrases the answer. Handlers compute every figure.
    Without AI, or if the provider fails, the keyword router answers instead."""
    def fallback(notice=''):
        return {**ask_module.answer(db, question), 'source': 'rules', 'notice': notice}
    if not configured():
        return fallback()
    findings = workspace(db)['findings']
    open_ = [f for f in findings if f['status'] not in OPEN and f['saving'] > 0]
    system = ('You are Stratus, a cloud cost assistant. Choose the data tools (at most three) that answer the question. '
              'If the question is not about cloud cost, savings, health, budgets, approvals or accounts, say briefly what you can help with and call no tool. ' + GUARD)
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': question}]
    try:
        first = complete(messages, tools=TOOLS, max_tokens=600)
        calls = [c for c in (first.get('tool_calls') or []) if c.get('function', {}).get('name') in ask_module.HANDLERS][:3]
        if not calls:
            text = _s(first.get('content'), 1500)
            if not text:
                raise AIError('AI returned an empty answer.')
            return {'topic': 'ai', 'answer': text, 'items': [], 'suggestions': ask_module.SUGGESTIONS, 'source': 'ai', 'notice': ''}
        messages.append({'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': c['id'], 'type': 'function', 'function': {'name': c['function']['name'], 'arguments': '{}'}} for c in calls]})
        items = []
        for call in calls:
            result = ask_module.HANDLERS[call['function']['name']](db, findings, open_)
            items += result['items']
            messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(result)})
        messages.append({'role': 'system', 'content': 'Answer in at most three sentences using only the figures in the tool results. '
                                                      'The matching items are shown under your answer, so do not list them.'})
        final = complete(messages, tools=TOOLS, tool_choice='none', max_tokens=800)
        text = _s(final.get('content'), 1500)
        if not text:
            raise AIError('AI returned an empty answer.')
    except AIError as exc:
        return fallback(f'{exc} Answered with the built-in rules instead.')
    seen, unique = set(), []
    for item in items:
        key = (item['label'], item['value'])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return {'topic': calls[0]['function']['name'], 'answer': text, 'items': unique[:8], 'suggestions': ask_module.SUGGESTIONS,
            'source': 'ai', 'notice': ''}


# --------------------------------------------------- 2. Monitor diagnosis
def diagnose_monitor(db: Session) -> dict:
    require()
    m = monitor(db)
    issues = m['issues'][:20]
    if not issues:
        return {'source': 'ai', 'summary': 'All checks passed. Every account and resource is reporting normally.', 'causes': []}
    data = {'status': m['status'], 'counts': m['counts'], 'accounts': m['accounts'], 'pipeline': m['pipeline'],
            'issues': [{k: i[k] for k in ('id', 'severity', 'scope', 'target', 'title', 'detail')} for i in issues]}
    out = _run(generate_json,
               'You are a cloud operations troubleshooter. Group related issues under the most probable root cause, order causes by urgency, '
               'and give concrete next steps a person can follow. At most 5 causes. issue_ids must be copied from the data.',
               data, '{"summary": string, "causes": [{"title": string, "explanation": string, "issue_ids": [string], "next_steps": [string]}]}')
    valid = {i['id'] for i in issues}
    causes = [{'title': _s(c.get('title'), 160), 'explanation': _s(c.get('explanation')),
               'issueIds': [x for x in _list(c.get('issue_ids'), 20, 200) if x in valid], 'nextSteps': _list(c.get('next_steps'))}
              for c in (out.get('causes') if isinstance(out.get('causes'), list) else [])[:5] if isinstance(c, dict)]
    return {'source': 'ai', 'summary': _s(out.get('summary')), 'causes': causes}


# ---------------------------------------------------- 3. Executive narrative
def report_narrative(db: Session) -> dict:
    require()
    d, m, ws = dashboard(db), monitor(db), workspace(db)
    top = sorted((f for f in ws['findings'] if f['status'] == 'Pending' and f['saving'] > 0), key=lambda f: -f['saving'])[:8]
    data = {'totals': d['totals'], 'byProvider': d['byProvider'], 'byEnvironment': d['byEnvironment'],
            'savingsFunnel': d['savings']['funnel'], 'savingsCounts': d['savings']['counts'], 'annualizedVerified': d['savings']['annualizedVerified'],
            'topOpportunities': [{k: f[k] for k in ('name', 'provider', 'env', 'kind', 'action', 'saving', 'risk', 'status')}
                                 | {'confidence': (f.get('confidence') or {}).get('level')} for f in top],
            'health': {'status': m['status'], 'counts': m['counts'],
                       'issues': [{k: i[k] for k in ('severity', 'target', 'title', 'detail')} for i in m['issues'][:6]]}}
    out = _run(generate_json,
               'You write a short executive summary of a cloud cost review for leadership: plain language, no jargon, no hype. '
               'Savings are monthly compute-only estimates at list prices; say so once. Recommend which decisions to take first and why.',
               data, '{"headline": string, "summary": [string, up to 3 short paragraphs], "decisions": [string, up to 4], "risks": [string, up to 4]}')
    return {'source': 'ai', 'headline': _s(out.get('headline'), 240), 'summary': _list(out.get('summary'), 3, 900),
            'decisions': _list(out.get('decisions'), 4), 'risks': _list(out.get('risks'), 4)}


# ---------------------------------------------------- 4. Approval assist
def approval_assist(db: Session, resource_id: str) -> dict:
    require()
    rec, res = _target(db, resource_id)
    if rec.finding['kind'] == 'Healthy':
        raise HTTPException(409, 'Healthy resources have no recommendation to review')
    out = _run(generate_json,
               'You help a reviewer decide whether to approve a cloud cost recommendation. Explain the blast radius of the proposed action for THIS resource, '
               'list what the reviewer must confirm before approving (owner, schedules, dependencies, peak jobs, data on disk) without claiming you know the answers, '
               'describe how to roll back, and draft a short approval note the reviewer can edit.',
               _context(db, rec, res),
               '{"blast_radius": string, "checks": [string, up to 6], "rollback": string, "approval_note": string}')
    return {'source': 'ai', 'blastRadius': _s(out.get('blast_radius')), 'checks': _list(out.get('checks'), 6),
            'rollback': _s(out.get('rollback')), 'approvalNote': _s(out.get('approval_note'), 800)}


# -------------------------------------------------- 5. Anomaly explanation
def explain_anomaly(db: Session, resource_id: str) -> dict:
    require()
    rec, res = _target(db, resource_id)
    name = res.data['name']
    points = resource_history(db, res.id, 30)
    account_id = res.data.get('accountId')
    events = db.scalars(select(AuditEvent).where(AuditEvent.org_id == org_of(db), AuditEvent.detail.contains(name)).order_by(AuditEvent.created_at.desc()).limit(10)).all()
    ledger = db.scalars(select(SavingsEntry).where(SavingsEntry.org_id == org_of(db), SavingsEntry.resource_id == res.id).order_by(SavingsEntry.implemented_at.desc()).limit(5)).all()
    syncs = db.scalars(select(SyncRun).where(SyncRun.org_id == org_of(db), SyncRun.account_id == account_id).order_by(SyncRun.started_at.desc()).limit(5)).all() if account_id else []
    data = {'resource': res.data, 'readings': points,
            'detected': [{'kind': h['kind'], 'detail': h['detail']} for h in anomalies([res.data], {res.id: points})],
            'recommendation': {'kind': rec.finding['kind'], 'status': rec.status},
            'recentActivity': [{'title': e.title, 'detail': e.detail, 'at': e.created_at.isoformat()} for e in events],
            'implementedChanges': [{'action': e.action, 'status': e.status, 'at': e.implemented_at.isoformat()} for e in ledger],
            'recentSyncs': [{'status': s.status, 'message': s.message, 'at': s.started_at.isoformat()} for s in syncs]}
    out = _run(generate_json,
               'You investigate why a cloud VM metric moved. From the readings and recent activity, give the most likely causes, each with the evidence in the data '
               'that supports it and how sure you are. Separate what the data shows from what you suspect. If the data cannot explain it, say so.',
               data, '{"summary": string, "likely_causes": [{"cause": string, "evidence": string, "confidence": "High"|"Medium"|"Low"}], "checks": [string, up to 5]}')
    causes = [{'cause': _s(c.get('cause'), 300), 'evidence': _s(c.get('evidence'), 500),
               'confidence': c.get('confidence') if c.get('confidence') in ('High', 'Medium', 'Low') else 'Low'}
              for c in (out.get('likely_causes') if isinstance(out.get('likely_causes'), list) else [])[:4] if isinstance(c, dict)]
    return {'source': 'ai', 'summary': _s(out.get('summary')), 'causes': causes, 'checks': _list(out.get('checks'), 5)}


# ----------------------------------------------------------- 7. Forecasting
def forecast_narrative(db: Session) -> dict:
    """Explains the statistical forecast. The projected numbers come from forecast.py; the model never produces its own."""
    require()
    f = forecast(db)
    if not f['fleet']['sufficient']:
        return {'source': 'ai', 'summary': 'There is not enough history to forecast yet. At least 3 daily readings are needed; history builds with every sync.',
                'budgetRisks': [], 'actions': [], 'caveats': []}
    pending = [x for x in workspace(db)['findings'] if x['status'] == 'Pending' and x['saving'] > 0]
    data = {'forecast': {**f, 'fleet': {**f['fleet'], 'series': f['fleet']['series'][-30:]}},
            'pendingSavingsPerMonth': sum(x['saving'] for x in pending), 'pendingRecommendations': len(pending)}
    out = _run(generate_json,
               'You explain a cloud spend forecast to a finance or engineering lead. The projected figures were computed by a straight-line trend; quote them, never produce '
               'your own projections. Say what the trend implies for each account that has a budget (use budgetStatus and daysToBudget); list budget_risks only for accounts whose budgetStatus is not No budget, and if no account has a budget, say that setting budgets would enable budget alerts, what likely drives it (growth in resource count '
               'or cost per resource: only if the data shows it), and which actions would help, referring to pending savings recommendations by total only. '
               'Be honest about low confidence, short history and coveragePct (the share of the run rate that has a trend; the rest is held flat, and new resources are not predicted). Costs are monthly run rate at on-demand list prices.',
               data, '{"summary": string, "budget_risks": [string, up to 5], "actions": [string, up to 4], "caveats": [string, up to 3]}')
    return {'source': 'ai', 'summary': _s(out.get('summary'), 1200), 'budgetRisks': _list(out.get('budget_risks'), 5),
            'actions': _list(out.get('actions'), 4), 'caveats': _list(out.get('caveats'), 3)}
