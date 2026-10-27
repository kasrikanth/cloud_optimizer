"""Spend by service and a read-only inventory of every resource a collector can see (AWS today).

This is visibility, not analysis: the savings rules still apply only to VMs. Data is stored per account and replaced on
each sync; a service the collector could not read this time keeps its previous rows instead of being wiped.
"""
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from .collectors import EMULATOR_MODES
from .models import CloudAccount, CloudAsset, ServiceCost, utcnow
from .tenant import org_of

NOT_ATTACHED = 'not attached'
MAX_ASSETS_RETURNED = 500


def store(db: Session, account, collection):
    """Save the optional extras of a collection. None means 'not collected this time'."""
    org, now = org_of(db), utcnow()
    if collection.spend is not None:
        db.execute(delete(ServiceCost).where(ServiceCost.org_id == org, ServiceCost.account_id == account.id))
        for row in collection.spend:
            db.add(ServiceCost(account_id=account.id, month=row['month'], service=row['service'], amount=row['amount'], captured_at=now))
    if collection.assets is not None and collection.asset_services:
        covered = set(collection.asset_services)
        db.execute(delete(CloudAsset).where(CloudAsset.org_id == org, CloudAsset.account_id == account.id, CloudAsset.service.in_(covered)))
        for a in collection.assets:
            if a['service'] in covered:
                db.add(CloudAsset(account_id=account.id, service=a['service'], asset_id=a['asset_id'], name=a['name'], region=a['region'],
                                  type=a['type'], state=a['state'], detail=a['detail'], captured_at=now))


def remove_for_account(db: Session, account_id: str):
    org = org_of(db)
    db.execute(delete(ServiceCost).where(ServiceCost.org_id == org, ServiceCost.account_id == account_id))
    db.execute(delete(CloudAsset).where(CloudAsset.org_id == org, CloudAsset.account_id == account_id))


def overview(db: Session) -> dict:
    org = org_of(db)
    accounts = {a.id: a for a in db.scalars(select(CloudAccount).where(CloudAccount.org_id == org).order_by(CloudAccount.name)).all()}
    costs = db.scalars(select(ServiceCost).where(ServiceCost.org_id == org)).all()
    assets = db.scalars(select(CloudAsset).where(CloudAsset.org_id == org).order_by(CloudAsset.service, CloudAsset.name)).all()

    months = sorted({c.month for c in costs})[-3:]
    current = months[-1] if months else None
    by_service, by_account, total = {}, {}, {m: 0.0 for m in months}
    for c in costs:
        if c.month not in total or c.account_id not in accounts:
            continue
        by_service.setdefault(c.service, {m: 0.0 for m in months})[c.month] += c.amount
        by_account.setdefault(c.account_id, {m: 0.0 for m in months})[c.month] += c.amount
        total[c.month] += c.amount
    rnd = lambda amounts: {m: round(v, 2) for m, v in amounts.items()}
    cur_total = total.get(current, 0) if current else 0
    spend_rows = sorted(({'service': s, 'amounts': rnd(a), 'share': round(a[current] / cur_total * 100, 1) if current and cur_total > 0 else 0}
                         for s, a in by_service.items()), key=lambda r: -(r['amounts'].get(current, 0) if current else 0))

    inventory = {}
    for a in assets:
        row = inventory.setdefault(a.service, {'service': a.service, 'count': 0, 'notAttached': 0})
        row['count'] += 1
        row['notAttached'] += a.state == NOT_ATTACHED
    spend_accounts = {c.account_id for c in costs}
    asset_counts = {}
    for a in assets:
        asset_counts[a.account_id] = asset_counts.get(a.account_id, 0) + 1
    captured = [c.captured_at for c in costs] + [a.captured_at for a in assets]
    return {
        'months': months, 'currentMonth': current,
        'monthToDate': bool(current and current == utcnow().strftime('%Y-%m')),
        'spend': {'total': rnd(total), 'byService': spend_rows,
                  'byAccount': sorted(({'id': i, 'name': accounts[i].name, 'amounts': rnd(a)} for i, a in by_account.items()),
                                      key=lambda r: -(r['amounts'].get(current, 0) if current else 0))},
        'inventory': {'total': len(assets), 'byService': sorted(inventory.values(), key=lambda r: -r['count'])},
        'assets': [{'id': a.id, 'accountId': a.account_id, 'account': accounts[a.account_id].name if a.account_id in accounts else '',
                    'service': a.service, 'assetId': a.asset_id, 'name': a.name, 'region': a.region, 'type': a.type, 'state': a.state,
                    'detail': a.detail} for a in assets[:MAX_ASSETS_RETURNED]],
        'assetsTruncated': len(assets) > MAX_ASSETS_RETURNED,
        'accounts': [{'id': a.id, 'name': a.name, 'provider': a.provider, 'mode': a.mode, 'hasSpend': a.id in spend_accounts,
                      'assetCount': asset_counts.get(a.id, 0)} for a in accounts.values()],
        'collectedAt': max(captured).isoformat() if captured else None,
        'emulatorAccounts': [a.name for a in accounts.values() if a.mode in EMULATOR_MODES],
        'note': 'Spend is the provider-reported billed cost (unblended) per service, including every service in the account. '
                'The current month is month to date. Inventory is read-only visibility: savings analysis still covers VMs only.',
    }
