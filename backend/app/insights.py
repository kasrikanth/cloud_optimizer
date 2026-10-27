"""Read-only views computed on demand: multi-cloud dashboard, service comparison, health monitor."""
from datetime import timedelta, timezone
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from .accounts import OPEN, account_rows
from .config import get_settings
from .history import anomalies, fleet_trend, recent
from .ledger import summary as ledger_summary
from .models import CloudAccount, Resource, Scan, utcnow
from .pricing import CLASSES, PRICING_MODELS
from .services import workspace
from .tenant import org_of

PROVIDERS = ['AWS', 'Azure', 'GCP']
STALE_HOURS, VERY_STALE_HOURS = 24, 72
SYNCABLE = ('demo', 'aws', 'azure', 'aws_emu', 'azure_emu')


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- dashboard
def dashboard(db: Session):
    ws = workspace(db)
    findings = ws['findings']
    accounts = account_rows(db, findings)
    open_ = [f for f in findings if f['status'] not in OPEN]
    total = sum(f['cost'] for f in findings)
    by_provider = []
    for p in PROVIDERS:
        mine = [f for f in findings if f['provider'] == p]
        linked = [a for a in accounts if a['provider'] == p]
        if not mine and not linked:
            continue
        mine_open = [f for f in mine if f['status'] not in OPEN]
        by_provider.append({
            'provider': p, 'accounts': len(linked), 'resources': len(mine),
            'monthlyCost': sum(f['cost'] for f in mine), 'costShare': round(sum(f['cost'] for f in mine) / total * 100) if total else 0,
            'potentialSavings': sum(f['saving'] for f in mine_open),
            'openRecommendations': len([f for f in mine_open if f['kind'] != 'Healthy']),
            'avgCpu': round(sum(f['cpu'] for f in mine) / len(mine)) if mine else None,
        })
    by_env = [{'env': e, 'resources': len([f for f in findings if f['env'] == e]),
               'monthlyCost': sum(f['cost'] for f in findings if f['env'] == e)}
              for e in ['Production', 'Staging', 'Development']]
    budget = sum(a['budgetUsd'] or 0 for a in accounts)
    budgeted_cost = sum(a['monthlyCost'] for a in accounts if a['budgetUsd'])
    return {
        'totals': {'accounts': len([a for a in accounts if a['id']]), 'resources': len(findings), 'monthlyCost': total,
                   'potentialSavings': sum(f['saving'] for f in open_),
                   'openRecommendations': len([f for f in open_ if f['kind'] != 'Healthy']),
                   'budget': budget, 'budgetedCost': budgeted_cost},
        'byProvider': by_provider, 'byEnvironment': by_env, 'accounts': accounts, 'lastScan': ws['lastScan'],
        'trend': fleet_trend(db), 'savings': ledger_summary(db, findings),
    }


# --------------------------------------------------------------- comparison
_TYPE_TO_CLASS = {t: c[0] for c in CLASSES for (t, _) in c[4].values()}
_CLASS = {c[0]: c for c in CLASSES}


def _arm_sibling(cls):
    return next((c for c in CLASSES if c[0].startswith('arm-') and c[2] == cls[2] and c[3] == cls[3]), None) if cls[0].startswith('gp-') else None


def comparison(db: Session):
    classes = []
    for cid, family, vcpu, mem, prices in CLASSES:
        cheapest = min(prices, key=lambda p: prices[p][1])
        low, high = min(v[1] for v in prices.values()), max(v[1] for v in prices.values())
        classes.append({'id': cid, 'family': family, 'vcpu': vcpu, 'memoryGb': mem,
                        'prices': {p: {'type': t, 'monthly': usd} for p, (t, usd) in prices.items()},
                        'cheapest': cheapest, 'spreadPct': round((high - low) / low * 100, 1)})
    names = {a.id: a.name for a in db.scalars(select(CloudAccount).where(CloudAccount.org_id == org_of(db))).all()}
    rows = []
    for f in workspace(db)['findings']:
        cid = _TYPE_TO_CLASS.get(f['type'])
        if not cid:
            continue
        cls = _CLASS[cid]
        current = cls[4].get(f['provider'], (None, None))[1]
        if current is None:
            continue
        best = min(cls[4], key=lambda p: cls[4][p][1])
        arm = _arm_sibling(cls)
        rows.append({
            'id': f['id'], 'name': f['name'], 'account': names.get(f.get('accountId'), ''), 'provider': f['provider'],
            'type': f['type'], 'classId': cid, 'listPrice': current,
            'cheapest': {'provider': best, 'type': cls[4][best][0], 'monthly': cls[4][best][1]},
            'differencePct': round((cls[4][best][1] - current) / current * 100, 1),
            'arm': {'type': arm[4][f['provider']][0], 'monthly': arm[4][f['provider']][1],
                    'savingsPct': round((current - arm[4][f['provider']][1]) / current * 100)} if arm else None,
        })
    return {'classes': classes, 'resources': rows, 'pricingModels': PRICING_MODELS,
            'disclaimer': 'Approximate on-demand Linux list prices for US regions at 730 hours/month. Illustrative only; check each provider\'s calculator. Moving clouds also changes networking, licensing and migration cost.'}


# ------------------------------------------------------------------ monitor
SEVERITY = {'critical': 0, 'warning': 1, 'info': 2}
AGENT_HINT = {
    'AWS': 'Install and configure the CloudWatch agent so memory metrics are published.',
    'Azure': 'Enable the Azure Monitor Agent (VM insights) so guest memory metrics are collected.',
    'GCP': 'Install the Ops Agent so memory metrics reach Cloud Monitoring.',
}


def _issue(sev, scope, target, title, detail, fix, resource_id=None):
    issue = {'id': f'{scope}:{target}:{title}', 'severity': sev, 'scope': scope, 'target': target,
             'title': title, 'detail': detail, 'fix': fix}
    if resource_id:
        issue['resourceId'] = resource_id  # lets the UI offer per-resource AI explanations
    return issue


def monitor(db: Session):
    settings = get_settings()
    now = utcnow()
    interval = timedelta(minutes=settings.sync_interval_minutes)
    issues = []
    db_ok = True
    try:
        db.execute(text('SELECT 1'))
    except Exception:
        db_ok = False
    org = org_of(db)
    resources = db.scalars(select(Resource).where(Resource.org_id == org).order_by(Resource.id)).all()
    accounts = db.scalars(select(CloudAccount).where(CloudAccount.org_id == org).order_by(CloudAccount.name)).all()
    per_account = {a.id: [] for a in accounts}
    loose = []
    snapshots = recent(db)

    for r in resources:
        d = r.data
        (per_account[d['accountId']] if d.get('accountId') in per_account else loose).append(r)
        name = d['name']
        age = (now - _aware(r.seen_at or r.updated_at)).total_seconds() / 3600
        if age >= STALE_HOURS:
            issues.append(_issue('critical' if age >= VERY_STALE_HOURS else 'warning', 'resource', name, 'Stale data',
                f'Last reported {int(age)} hours ago.',
                ['Check that the account sync is still running.', 'Open Cloud accounts and press Sync now; read the error if it fails.', 'For import accounts, re-import inventory to refresh now.'], d['id']))
        gaps, fixes = [], []
        if d['memory'] is None:
            gaps.append('memory metrics missing')
            fixes.append(AGENT_HINT.get(d['provider'], 'Enable guest memory metrics.'))
        if d['coverage'] < 95:
            gaps.append(f"metric coverage {d['coverage']:g}% (needs 95%)")
            fixes.append('Check monitoring agent health and metric retention; gaps often come from a stopped agent or a recently created VM.')
        if d['days'] < 14:
            gaps.append(f"only {d['days']} observation days (needs 14)")
            fixes.append('Wait until 14 days of data exist before acting on savings for this resource.')
        if gaps:
            issues.append(_issue('warning' if d['memory'] is None or d['coverage'] < 95 else 'info', 'resource', name,
                'Telemetry incomplete', 'Savings are withheld: ' + '; '.join(gaps) + '.', fixes, d['id']))
        pressure = []
        if d['cpu'] >= 80:
            pressure.append(f"P95 CPU {d['cpu']:g}%")
        if d['memory'] is not None and d['memory'] >= 85:
            pressure.append(f"P95 memory {d['memory']:g}%")
        if pressure:
            hot = d['cpu'] >= 95 or (d['memory'] is not None and d['memory'] >= 95)
            issues.append(_issue('critical' if hot else 'warning', 'resource', name, 'Resource under pressure',
                ', '.join(pressure) + '. Risk of throttling or out-of-memory.',
                ['Do not downsize this resource.', 'Inspect recent load and consider scaling up or out.', 'Add an alert at 80% CPU / 85% memory if none exists.'], d['id']))

    for hit in anomalies([r.data for r in resources], snapshots):
        r = hit['resource']
        issues.append(_issue('warning', 'resource', r['name'], 'Unusual CPU' if hit['kind'] == 'cpu' else 'Cost jump', hit['detail'],
            ['Compare with deployments, traffic or batch jobs in the same window.', 'Open the resource history from Opportunities to see the trend.', 'If this is expected growth, no action is needed; the baseline adapts.']
            if hit['kind'] == 'cpu' else ['Check whether the instance was resized or replaced.', 'Confirm the change was planned and approved.'], r['id']))

    for a in accounts:
        mine = per_account[a.id]
        if a.last_sync_status == 'Failed':
            issues.append(_issue('critical', 'account', a.name, 'Sync failed', a.last_sync_error or 'The last sync failed.',
                ['Open Cloud accounts and press Test connection.', 'Check that the credentials are active and the role keeps read access.', 'Rotate the credentials with Edit if they were revoked.']))
        elif a.mode in SYNCABLE and settings.sync_enabled and a.last_sync_at and now - _aware(a.last_sync_at) > interval * 3:
            issues.append(_issue('warning', 'account', a.name, 'Sync overdue', f'No sync for {int((now - _aware(a.last_sync_at)).total_seconds() // 3600)} hours.',
                ['Check that the backend is running and SYNC_ENABLED is true.', 'Press Sync now to run it immediately.']))
        if not mine and a.last_sync_status != 'Failed':
            issues.append(_issue('warning', 'account', a.name, 'No data received', f'No resources have been reported for this {a.provider} account yet.',
                ['Press Sync now if this account uses a live or demo collector.', f'For import accounts, import inventory with accountId {a.id}.']))
        if a.budget_usd:
            cost = sum(r.data['cost'] for r in mine)
            used = cost / a.budget_usd * 100
            if used >= 90:
                issues.append(_issue('critical' if used >= 100 else 'warning', 'account', a.name, 'Over budget' if used >= 100 else 'Approaching budget',
                    f'Run rate ${cost:,.0f} is {used:.0f}% of the ${a.budget_usd:,.0f} monthly budget.',
                    ['Review open recommendations for this account on the Opportunities page.', 'Approve and implement the largest savings first.', 'Raise the budget if the growth is planned.']))
    if loose:
        issues.append(_issue('info', 'account', 'Unassigned resources', 'Resources without an account',
            f'{len(loose)} resource(s) are not linked to a cloud account.',
            ['Add accountId to these records and re-import, or import them through a specific account.']))

    if not db_ok:
        issues.append(_issue('critical', 'pipeline', 'Database', 'Database unreachable', 'The API cannot query PostgreSQL.',
            ['Run docker compose ps and confirm the postgres container is healthy.', 'Check DATABASE_URL in the root .env.']))
    scan = db.scalar(select(Scan).where(Scan.org_id == org).order_by(Scan.created_at.desc()).limit(1))
    if resources and (scan is None or (now - _aware(scan.created_at)).total_seconds() > 86400):
        issues.append(_issue('info', 'pipeline', 'Analysis', 'No recent analysis', 'Recommendations may not reflect the latest rules.', ['Press Run analysis on the Opportunities page.']))

    issues.sort(key=lambda i: (SEVERITY[i['severity']], i['scope'], i['target']))
    counts = {s: len([i for i in issues if i['severity'] == s]) for s in SEVERITY}

    def acct_state(a, mine):
        if a.last_sync_status == 'Failed':
            return 'Sync failed'
        if not mine:
            return 'Awaiting data'
        names = {r.data['name'] for r in mine}
        sev = [i['severity'] for i in issues if i['scope'] in ('resource',) and i['target'] in names] + [i['severity'] for i in issues if i['scope'] == 'account' and i['target'] == a.name]
        return 'Critical' if 'critical' in sev else 'Attention' if 'warning' in sev else 'Healthy'
    account_health = [{'id': a.id, 'name': a.name, 'provider': a.provider, 'mode': a.mode, 'resources': len(per_account[a.id]),
                       'lastReported': max((_aware(r.seen_at or r.updated_at) for r in per_account[a.id]), default=None),
                       'lastSyncAt': _aware(a.last_sync_at).isoformat() if a.last_sync_at else None,
                       'state': acct_state(a, per_account[a.id])} for a in accounts]
    for row in account_health:
        row['lastReported'] = row['lastReported'].isoformat() if row['lastReported'] else None
    overall = 'Critical' if counts['critical'] else 'Attention' if counts['warning'] else 'Healthy'
    return {'checkedAt': now.isoformat(), 'status': overall, 'counts': counts, 'issues': issues, 'accounts': account_health,
            'pipeline': {'database': 'ok' if db_ok else 'down', 'executionMode': 'dry-run',
                         'llmConfigured': bool(settings.llm_api_key and settings.llm_model),
                         'syncEnabled': settings.sync_enabled, 'syncIntervalMinutes': settings.sync_interval_minutes,
                         'secretsConfigured': bool(settings.secrets_key),
                         'lastScan': _aware(scan.created_at).isoformat() if scan else None},
            'thresholds': {'staleHours': STALE_HOURS, 'cpuPressure': 80, 'memoryPressure': 85}}
