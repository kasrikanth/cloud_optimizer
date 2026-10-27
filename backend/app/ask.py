"""Ask Stratus: plain-language questions answered from the organization's own data.

Deliberately not an LLM. Every number comes from the same rules, ledger and monitor the rest of the app uses, so an
answer can be traced to a page. A keyword router picks the topic; each handler reads live data.
"""
from sqlalchemy.orm import Session
from .accounts import OPEN, account_rows
from .insights import comparison, monitor
from .ledger import summary as ledger_summary
from .services import workspace

money = lambda n: f'${n:,.0f}'
SUGGESTIONS = ['How much can we save?', 'Which resources are idle?', 'What is wrong right now?', 'Which cloud costs the most?',
               'What has been saved so far?', 'Which accounts are over budget?', 'What needs approval?']
TOPICS = [
    ('impact', ('verified', 'realized', 'realised', 'impact', 'roi', 'saved so far', 'results', 'achieved')),
    ('budget', ('budget', 'forecast', 'overspend', 'over budget')),
    ('compare', ('compare', 'cheaper', 'cheapest', 'versus', ' vs ', 'switch cloud', 'arm', 'graviton')),
    ('idle', ('idle', 'unused', 'switch off', 'shut down', 'turn off', 'stop ')),
    ('oversized', ('oversize', 'rightsiz', 'right-siz', 'resize', 'downsize', 'too big', 'too large')),
    ('health', ('health', 'issue', 'problem', 'wrong', 'broken', 'alert', 'incident', 'fail', 'stale', 'monitor')),
    ('approval', ('approv', 'pending', 'waiting', 'review', 'to do', 'todo')),
    ('risk', ('risk', 'production', 'critical', 'dangerous', 'safe')),
    ('accounts', ('account', 'connected', 'subscription', 'project')),
    ('spend', ('spend', 'cost', 'expensive', 'biggest', 'bill', 'run rate', 'most')),
    ('savings', ('save', 'saving', 'reduce', 'cut', 'opportunit', 'optimi')),
]


def _item(label, value, detail='', link=''):
    return {'label': label, 'value': value, 'detail': detail, 'link': link}


def answer(db: Session, question: str) -> dict:
    q = f' {question.lower()} '
    scores = [(sum(k in q for k in keys), -i, topic) for i, (topic, keys) in enumerate(TOPICS)]
    best = max(scores)
    topic = best[2] if best[0] else 'help'
    findings = workspace(db)['findings']
    open_ = [f for f in findings if f['status'] not in OPEN and f['saving'] > 0]
    handler = globals()['_' + topic]
    result = handler(db, findings, open_)
    return {'topic': topic, 'suggestions': SUGGESTIONS, **result}


def _help(db, findings, open_):
    return {'answer': 'I answer from your own data. Try one of these questions.', 'items': []}


def _savings(db, findings, open_):
    top = sorted(open_, key=lambda f: -f['saving'])[:5]
    if not open_:
        return {'answer': 'There are no open savings recommendations right now.', 'items': []}
    return {'answer': f'{len(open_)} open recommendations could save about {money(sum(f["saving"] for f in open_))} per month. The biggest five:',
            'items': [_item(f['name'], money(f['saving']) + '/mo', f"{f['action']} · {f['risk']} risk", '#opportunities') for f in top]}


def _idle(db, findings, open_):
    rows = [f for f in open_ if f['kind'] == 'Idle resource']
    if not rows:
        return {'answer': 'No idle resources found. Idle means very low CPU, memory and network on a non-production, non-critical VM.', 'items': []}
    return {'answer': f'{len(rows)} idle resource(s) could save {money(sum(f["saving"] for f in rows))} per month if stopped. Confirm ownership first.',
            'items': [_item(f['name'], money(f['saving']) + '/mo', f"CPU {f['cpu']:g}% · {f['env']} · confidence {f.get('confidence', {}).get('level', '—')}", '#opportunities') for f in rows]}


def _oversized(db, findings, open_):
    rows = sorted([f for f in open_ if f['kind'] == 'Oversized resource'], key=lambda f: -f['saving'])
    if not rows:
        return {'answer': 'No oversized resources found.', 'items': []}
    return {'answer': f'{len(rows)} resource(s) look oversized, worth {money(sum(f["saving"] for f in rows))} per month if resized.',
            'items': [_item(f['name'], money(f['saving']) + '/mo', f"{f['type']} · CPU {f['cpu']:g}% · {f['risk']} risk", '#opportunities') for f in rows[:6]]}


def _spend(db, findings, open_):
    total = sum(f['cost'] for f in findings)
    by = {}
    for f in findings:
        by[f['provider']] = by.get(f['provider'], 0) + f['cost']
    top = sorted(findings, key=lambda f: -f['cost'])[:4]
    return {'answer': f'Monthly compute run rate is {money(total)} across {len(findings)} resources.',
            'items': [_item(p, money(c), f'{round(c / total * 100) if total else 0}% of spend', '#overview') for p, c in sorted(by.items(), key=lambda x: -x[1])]
            + [_item(f['name'], money(f['cost']) + '/mo', f"{f['provider']} · {f['type']}", '#opportunities') for f in top]}


def _health(db, findings, open_):
    m = monitor(db)
    if not m['issues']:
        return {'answer': 'All checks passed. Every account and resource is reporting normally.', 'items': []}
    return {'answer': f"Status is {m['status']}: {m['counts']['critical']} critical, {m['counts']['warning']} warning, {m['counts']['info']} info.",
            'items': [_item(f"{i['title']} · {i['target']}", i['severity'].title(), i['fix'][0], '#monitor') for i in m['issues'][:6]]}


def _compare(db, findings, open_):
    c = comparison(db)
    cheaper = [r for r in c['resources'] if r['differencePct'] < -1]
    arm = [r for r in c['resources'] if r['arm']]
    spread = max((x['spreadPct'] for x in c['classes']), default=0)
    return {'answer': f"Across comparable sizes the clouds differ by at most {spread:g}% on list price, so moving clouds rarely pays by itself. "
                      f"{len(cheaper)} of {len(c['resources'])} resources have a cheaper equivalent elsewhere; {len(arm)} could try Arm instances.",
            'items': [_item(r['name'], f"{r['differencePct']}%", f"{r['provider']} {r['type']} → {r['cheapest']['provider']} {r['cheapest']['type']}", '#compare') for r in cheaper[:4]]
            + [_item(r['name'], f"−{r['arm']['savingsPct']}%", f"{r['type']} → {r['arm']['type']} (Arm)", '#compare') for r in arm[:3]]}


def _budget(db, findings, open_):
    rows = [a for a in account_rows(db, findings) if a['budgetUsd']]
    if not rows:
        return {'answer': 'No budgets are set yet. Add one under Cloud accounts → Edit.', 'items': []}
    over = [a for a in rows if a['utilization'] >= 100]
    return {'answer': f'{len(over)} of {len(rows)} budgeted accounts are over budget.',
            'items': [_item(a['name'], f"{a['utilization']}%", f"{money(a['monthlyCost'])} of {money(a['budgetUsd'])}", '#accounts') for a in sorted(rows, key=lambda a: -a['utilization'])]}


def _impact(db, findings, open_):
    s = ledger_summary(db, findings)
    f = s['funnel']
    return {'answer': f"Verified savings so far: {money(f['verified'])} per month ({money(s['annualizedVerified'])} per year) from {s['counts']['verified']} implemented change(s). "
                      f"{s['counts']['awaiting']} more await verification.",
            'items': [_item('Identified', money(f['identified']) + '/mo', 'Open recommendations', '#savings'), _item('Approved', money(f['approved']) + '/mo', 'Approved or simulated', '#savings'),
                      _item('Implemented', money(f['implemented']) + '/mo', 'Awaiting verification', '#savings'), _item('Verified', money(f['verified']) + '/mo', 'Confirmed by later data', '#savings')]}


def _approval(db, findings, open_):
    pending = [f for f in findings if f['status'] == 'Pending' and f['saving'] > 0]
    approved = [f for f in findings if f['status'] == 'Approved']
    return {'answer': f'{len(pending)} recommendation(s) await review and {len(approved)} approved plan(s) are ready to simulate or implement.',
            'items': [_item(f['name'], money(f['saving']) + '/mo', f['action'], '#opportunities') for f in sorted(pending, key=lambda f: -f['saving'])[:5]]}


def _risk(db, findings, open_):
    high = [f for f in open_ if f['risk'] == 'High']
    return {'answer': f'{len(high)} open recommendation(s) are high risk because they touch production or critical workloads. Plan a maintenance window and a recovery path first.',
            'items': [_item(f['name'], money(f['saving']) + '/mo', f"{f['env']} · {f['action']}", '#opportunities') for f in high]}


def _accounts(db, findings, open_):
    rows = [a for a in account_rows(db, findings) if a['id']]
    return {'answer': f'{len(rows)} cloud account(s) are connected.',
            'items': [_item(a['name'], money(a['monthlyCost']) + '/mo', f"{a['provider']} · {a['resources']} resources · {a['mode']}", '#accounts') for a in rows]}


# Topic handlers by name. ai_features.py exposes them to the model as tools, so the model routes but never computes.
HANDLERS = {name: globals()['_' + name] for name, _ in TOPICS}
