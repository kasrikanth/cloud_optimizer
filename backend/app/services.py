from datetime import timedelta
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session
from fastapi import HTTPException
from .accounts import ensure_accounts
from .history import confidence, record_snapshots, recent
from .ledger import add_entry, verify as verify_ledger
from .models import Resource, Recommendation, AuditEvent, Scan, utcnow
from .rules import evaluate
from .tenant import org_of

# A routine collector sync only invalidates approvals when one of these changes (or the finding itself changes).
# Metric noise such as P95 CPU moving from 3.1% to 3.4% must not erase a reviewer's decision.
MATERIAL_FIELDS = ('name', 'provider', 'accountId', 'region', 'type', 'env', 'owner', 'critical', 'cost', 'targetCost')


def writer_lock(db: Session):
    # Serialize one organization's writes across API workers so imports cannot race with approvals.
    # Other organizations are not blocked. PostgreSQL releases this transaction-scoped lock on commit/rollback.
    if db.bind.dialect.name == 'postgresql':
        # PostgreSQL-compatible gateways may not infer an untyped parameter inside hashtext.
        db.execute(text('SELECT pg_advisory_xact_lock(88022026, hashtext(CAST(:org AS text)))'), {'org': org_of(db)})


def audit(db: Session, title: str, detail: str, actor='system'):
    db.add(AuditEvent(title=title, detail=detail, actor=actor))


def analyze(db: Session, changed_ids=None):
    changed_ids = changed_ids or set()
    org = org_of(db)
    resources = db.scalars(select(Resource).where(Resource.org_id == org)).all()
    count = 0
    for resource in resources:
        finding = evaluate(resource.data)
        count += finding['kind'] != 'Healthy'
        rec = db.get(Recommendation, (org, resource.id))
        if rec is None:
            db.add(Recommendation(resource_id=resource.id, finding=finding))
        elif rec.status == 'Implemented' and resource.id not in changed_ids:
            # The change was made; wait for the ledger to verify it instead of reopening the recommendation.
            rec.finding = finding
        elif rec.finding != finding or resource.id in changed_ids:
            rec.finding = finding
            rec.status = 'Pending'
            rec.reviewer = None
            rec.version += 1
            rec.updated_at = utcnow()
    db.add(Scan(count=len(resources), findings=count))
    db.flush()
    return {'resources': len(resources), 'findings': count}


def delete_resources(db: Session, ids):
    org, ids = org_of(db), list(ids)
    for start in range(0, len(ids), 400):
        chunk = ids[start:start + 400]
        db.execute(delete(Recommendation).where(Recommendation.org_id == org, Recommendation.resource_id.in_(chunk)))
        db.execute(delete(Resource).where(Resource.org_id == org, Resource.id.in_(chunk)))


def ingest(db: Session, payload, source='import', actor='system', material_only=False,
           prune_account=None, history=None, snapshot_gap=timedelta(seconds=60), label='Inventory imported', note=''):
    writer_lock(db)
    org = org_of(db)
    data = [{k: v for k, v in r.model_dump().items() if k != 'accountId' or v is not None} for r in payload.resources]
    ensure_accounts(db, data, actor)
    ids = {r['id'] for r in data}
    removed = set()
    if payload.replace:
        # Audit history deliberately survives inventory replacement.
        removed |= {rid for rid in db.scalars(select(Resource.id).where(Resource.org_id == org)) if rid not in ids}
    if prune_account:
        removed |= {r.id for r in db.scalars(select(Resource).where(Resource.org_id == org)).all() if r.data.get('accountId') == prune_account and r.id not in ids}
    verify_ledger(db, removed, {v['id']: v for v in data})
    if removed:
        delete_resources(db, removed)
    changed = set()
    now = utcnow()
    for values in data:
        resource = db.get(Resource, (org, values['id']))
        if resource is None:
            resource = Resource(id=values['id'], data=values, source=source)
            db.add(resource)
            changed.add(resource.id)
        elif resource.data != values:
            if not material_only or any(resource.data.get(k) != values.get(k) for k in MATERIAL_FIELDS):
                changed.add(resource.id)
            resource.data = values
            resource.source = source
            resource.updated_at = now
        resource.seen_at = now
    db.flush()
    record_snapshots(db, data, history, snapshot_gap)
    result = analyze(db, changed)
    audit(db, label, note + (f"{len(data)} records received from {source}. {len(changed)} changed; {len(removed)} removed." if material_only
          else f"{len(data)} records received from {source}. Changed-resource approvals invalidated."), actor)
    return {**result, 'received': len(data), 'removed': len(removed)}


def workspace(db: Session):
    org = org_of(db)
    resources = db.scalars(select(Resource).where(Resource.org_id == org).order_by(Resource.id)).all()
    findings = {r.resource_id: r for r in db.scalars(select(Recommendation).where(Recommendation.org_id == org)).all()}
    log = db.scalars(select(AuditEvent).where(AuditEvent.org_id == org).order_by(AuditEvent.created_at.desc()).limit(200)).all()
    scan = db.scalar(select(Scan).where(Scan.org_id == org).order_by(Scan.created_at.desc()).limit(1))
    snaps = recent(db)
    rows = []
    for r in resources:
        rec = findings.get(r.id)
        if not rec:
            continue
        row = {**r.data, **rec.finding, 'status': rec.status, 'version': rec.version, 'generation': rec.generation,
               'reviewer': rec.reviewer, 'source': r.source}
        if rec.finding['saving'] > 0:
            row['confidence'] = confidence(r.data, snaps.get(r.id, []), rec.finding['kind'])
        rows.append(row)
    return {
        'resources': [r.data for r in resources],
        'findings': rows,
        'log': [{'id': e.id, 'title': e.title, 'detail': e.detail, 'actor': e.actor,
                 'time': e.created_at.isoformat()} for e in log],
        'lastScan': scan.created_at.isoformat() if scan else None,
    }


def decide(db: Session, resource_id, request, actor='system'):
    writer_lock(db)
    org = org_of(db)
    rec = db.get(Recommendation, (org, resource_id))
    resource = db.get(Resource, (org, resource_id))
    if not rec or not resource:
        raise HTTPException(404, 'Recommendation not found')
    if rec.version != request.expected_version or rec.generation != request.expected_generation:
        raise HTTPException(409, 'This recommendation changed. Refresh and review the latest evidence.')
    if rec.finding['kind'] == 'Healthy':
        raise HTTPException(409, 'Healthy resources have no actionable recommendation')
    old_status = rec.status
    action = request.action
    if action == 'approve':
        if rec.status != 'Pending' or rec.finding['saving'] <= 0:
            raise HTTPException(409, 'Only pending savings recommendations can be approved')
        if not request.reviewer.strip():
            raise HTTPException(422, 'Reviewer name is required')
        rec.status, rec.reviewer = 'Approved', request.reviewer.strip()
        title = 'Plan approved'
    elif action == 'dismiss':
        if rec.status != 'Pending':
            raise HTTPException(409, 'Only pending recommendations can be dismissed')
        rec.status, title = 'Dismissed', 'Recommendation dismissed'
    elif action == 'reopen':
        if rec.status == 'Pending':
            raise HTTPException(409, 'Recommendation is already pending')
        if rec.status == 'Implemented':
            raise HTTPException(409, 'Implemented changes cannot be reopened. The next sync verifies the result.')
        rec.status, rec.reviewer, title = 'Pending', None, 'Recommendation reopened'
    elif action == 'implement':
        if rec.status not in ('Approved', 'Simulated'):
            raise HTTPException(409, 'Approve the plan before marking it implemented')
        rec.status, title = 'Implemented', 'Marked implemented'
        add_entry(db, rec, resource.data, actor)
    else:
        if rec.status != 'Approved':
            raise HTTPException(409, 'Approve the current plan before simulating it')
        # There is intentionally no cloud executor in this MVP.
        rec.status, title = 'Simulated', 'Execution simulated'
    rec.version += 1
    rec.updated_at = utcnow()
    detail = f"{resource.data['name']}: {old_status} → {rec.status}; {rec.finding['action']}."
    if rec.reviewer:
        detail += f' Reviewer: {rec.reviewer}.'
    if action == 'simulate':
        detail += ' Dry run only. No provider request sent; measured savings remain $0.'
    if action == 'implement':
        detail += ' The next sync of this account verifies the saving.'
    audit(db, title, detail, actor)
    db.flush()
    return {'status': rec.status, 'version': rec.version, 'mode': 'dry-run'}
