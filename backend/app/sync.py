"""Account sync: run a collector, ingest the result, record the run. Also the background schedule."""
import asyncio
import logging
from datetime import timedelta
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from . import cloud_services
from .accounts import get_account
from .collectors import SIMULATED_MODES, CollectorError, get_collector
from .config import get_settings
from .db import SessionLocal
from .history import prune
from .ledger import verify as verify_ledger
from .models import CloudAccount, Resource, SavingsEntry, SyncRun, utcnow
from .pricing import smaller
from .schemas import InventoryInput
from .services import analyze, audit, delete_resources, ingest, writer_lock
from .tenant import bind, org_of
from .vault import redact, unseal

log = logging.getLogger('stratus.sync')
LIVE_GAP = timedelta(hours=5)  # real collectors report slowly changing P95 values; do not store near-duplicates
SYNCABLE = ('demo', 'aws', 'azure', 'aws_emu', 'azure_emu')


def _credentials(account) -> dict:
    return unseal(account.credentials_enc) if account.credentials_enc else {}


def _collector(account):
    collector = get_collector(account.mode)
    if collector is None:
        raise HTTPException(409, 'This account receives data by JSON import, so there is nothing to sync.')
    return collector


def _apply_demo_changes(db: Session, account, collection):
    """A demo account models a cloud: once a person marks a change implemented, later syncs show the VM stopped,
    resized or rescheduled, the way a real cloud would after they made the change."""
    entries = db.scalars(select(SavingsEntry).where(SavingsEntry.org_id == org_of(db), SavingsEntry.account_id == account.id, SavingsEntry.status.in_(('Implemented', 'Verified')))
                         .order_by(SavingsEntry.implemented_at)).all()
    by_resource = {}
    for entry in entries:
        by_resource.setdefault(entry.resource_id, []).append(entry.action)
    kept = []
    for row in collection.resources:
        for action in by_resource.get(row['id'], []):
            if action == 'Stop VM':
                row = None
                break
            if action == 'Resize VM' and smaller(row['type']):
                name, price = smaller(row['type'])
                nxt = smaller(name)
                row = {**row, 'type': name, 'cost': price, 'targetCost': nxt[1] if nxt else price,
                       'cpu': min(99.0, round(row['cpu'] * 2, 1)), 'memory': None if row['memory'] is None else min(99.0, round(row['memory'] * 2, 1))}
            elif action == 'Schedule downtime':
                row = {**row, 'cost': round(row['cost'] * 220 / row['hours']), 'hours': 220}
        if row is not None:
            kept.append(row)
    collection.resources = kept


def test_connection(db: Session, account_id: str) -> dict:
    account = get_account(db, account_id)
    creds = _credentials(account)
    try:
        return {'ok': True, 'message': _collector(account).test(account, creds)}
    except CollectorError as exc:
        return {'ok': False, 'message': redact(str(exc), creds)}


def run_sync(db: Session, account_id: str, trigger='manual', actor='system') -> dict:
    account = get_account(db, account_id)
    collector = _collector(account)
    creds = _credentials(account)
    account_name = account.name
    status, message, count, removed = 'Success', '', 0, 0
    try:
        collection = collector.collect(account, creds)
        if account.mode in SIMULATED_MODES:
            _apply_demo_changes(db, account, collection)
        if collection.warnings:
            status, message = 'Partial', '; '.join(collection.warnings[:3])
        note = f'{account_name}: '
        writer_lock(db)
        if collection.resources:
            result = ingest(db, InventoryInput(resources=collection.resources), source=account.mode, actor=actor, material_only=True,
                            prune_account=account.id, history=collection.history, label='Account synced', note=note,
                            snapshot_gap=timedelta(seconds=60) if account.mode in SIMULATED_MODES else LIVE_GAP)
            count, removed = result['received'], result['removed']
        else:
            gone = {r.id for r in db.scalars(select(Resource).where(Resource.org_id == org_of(db))).all() if r.data.get('accountId') == account.id}
            verify_ledger(db, gone, {})
            delete_resources(db, gone)
            analyze(db)
            audit(db, 'Account synced', f'{note}0 running VMs found; {len(gone)} removed.', actor)
            removed = len(gone)
        cloud_services.store(db, account, collection)
        prune(db)
    except (CollectorError, ValidationError, HTTPException, Exception) as exc:
        db.rollback()  # discard any partial ingest; the run itself is recorded below
        if isinstance(exc, CollectorError):
            message = redact(str(exc), creds)
        elif isinstance(exc, ValidationError):
            message = 'The collector returned data the optimizer could not validate.'
        elif isinstance(exc, HTTPException):
            message = str(exc.detail)
        else:
            log.exception('sync failed for %s', account_id)
            message = f'Unexpected {type(exc).__name__} during sync. See the server log.'
        status, count, removed = 'Failed', 0, 0
    now = utcnow()
    account = get_account(db, account_id)
    db.add(SyncRun(account_id=account_id, trigger=trigger, status=status, resources=count, message=message[:300], finished_at=now))
    account.last_sync_at, account.last_sync_status = now, status
    account.last_sync_error = message[:300] if status == 'Failed' else None
    db.flush()
    return {'status': status, 'resources': count, 'removed': removed, 'message': message[:300]}


def recent_runs(db: Session, account_id: str, limit=20) -> list[dict]:
    get_account(db, account_id)
    rows = db.scalars(select(SyncRun).where(SyncRun.org_id == org_of(db), SyncRun.account_id == account_id)
                      .order_by(SyncRun.started_at.desc()).limit(limit)).all()
    return [{'id': r.id, 'trigger': r.trigger, 'status': r.status, 'resources': r.resources, 'message': r.message,
             'startedAt': r.started_at.isoformat(), 'finishedAt': r.finished_at.isoformat() if r.finished_at else None} for r in rows]


def _due(account, interval: timedelta) -> bool:
    if account.mode not in SYNCABLE:
        return False
    if account.last_sync_at is None:
        return True
    last = account.last_sync_at if account.last_sync_at.tzinfo else account.last_sync_at.replace(tzinfo=utcnow().tzinfo)
    return utcnow() - last >= interval


def sync_due() -> int:
    """Sync every account whose last run is older than the interval. Safe to call from several workers."""
    interval = timedelta(minutes=get_settings().sync_interval_minutes)
    with SessionLocal() as db:
        due = [(a.id, a.org_id) for a in db.scalars(select(CloudAccount)).all() if _due(a, interval)]
    done = 0
    for account_id, org_id in due:
        try:
            with SessionLocal.begin() as db:
                bind(db, org_id)  # each account syncs inside its own organization
                account = db.get(CloudAccount, account_id)
                if account and _due(account, interval):  # re-check: another worker may have just synced it
                    run_sync(db, account_id, 'schedule', 'scheduler')
                    done += 1
        except Exception:
            log.exception('scheduled sync failed for %s', account_id)
    return done


async def scheduler():
    await asyncio.sleep(5)
    while True:
        try:
            await run_in_threadpool(sync_due)
        except Exception:
            log.exception('scheduler iteration failed')
        await asyncio.sleep(60)
