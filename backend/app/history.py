"""Metric history: snapshots, evidence-based confidence, anomaly detection and the fleet cost trend."""
import statistics
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from .models import MetricSnapshot, utcnow
from .tenant import org_of
from .rules import evaluate

RETENTION_DAYS = 90


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def record_snapshots(db: Session, resources: list[dict], history: dict | None = None, min_gap=timedelta(seconds=60)):
    """One reading per resource per ingest. Demo collectors may backfill history for resources never seen before."""
    ids = [r['id'] for r in resources]
    latest = dict(db.execute(select(MetricSnapshot.resource_id, func.max(MetricSnapshot.captured_at))
                             .where(MetricSnapshot.org_id == org_of(db), MetricSnapshot.resource_id.in_(ids)).group_by(MetricSnapshot.resource_id)).all()) if ids else {}
    now = utcnow()
    for r in resources:
        last = latest.get(r['id'])
        if last is None and history and r['id'] in history:
            for p in history[r['id']]:
                db.add(MetricSnapshot(resource_id=r['id'], account_id=r.get('accountId'), captured_at=p['captured_at'],
                                      cpu=p['cpu'], memory=p['memory'], network=p['network'], cost=p['cost']))
        elif last is not None and now - _aware(last) < min_gap:
            continue
        db.add(MetricSnapshot(resource_id=r['id'], account_id=r.get('accountId'), captured_at=now, cpu=r['cpu'],
                              memory=r['memory'], network=r['network'], cost=r['cost']))


def prune(db: Session):
    db.execute(delete(MetricSnapshot).where(MetricSnapshot.org_id == org_of(db), MetricSnapshot.captured_at < utcnow() - timedelta(days=RETENTION_DAYS)))


def recent(db: Session, limit=14) -> dict[str, list[dict]]:
    """The last `limit` snapshots per resource, oldest first."""
    rn = func.row_number().over(partition_by=MetricSnapshot.resource_id, order_by=MetricSnapshot.captured_at.desc()).label('rn')
    sub = select(MetricSnapshot.resource_id, MetricSnapshot.captured_at, MetricSnapshot.cpu, MetricSnapshot.memory,
                 MetricSnapshot.network, MetricSnapshot.cost, rn).where(MetricSnapshot.org_id == org_of(db)).subquery()
    out: dict[str, list[dict]] = {}
    for row in db.execute(select(sub).where(sub.c.rn <= limit).order_by(sub.c.resource_id, sub.c.captured_at)):
        out.setdefault(row.resource_id, []).append(dict(at=_aware(row.captured_at), cpu=row.cpu, memory=row.memory, network=row.network, cost=row.cost))
    return out


def confidence(data: dict, snaps: list[dict], kind: str) -> dict:
    """How consistently the recommendation's rule held across recent readings, not a statistical guarantee."""
    n = len(snaps)
    if not n:
        return {'level': 'Low', 'samples': 0, 'consistency': 0}
    same = sum(1 for s in snaps if evaluate({**data, 'cpu': s['cpu'], 'memory': s['memory'], 'network': s['network']})['kind'] == kind)
    frac = same / n
    level = 'High' if n >= 7 and frac >= 0.9 else 'Medium' if n >= 3 and frac >= 0.7 else 'Low'
    return {'level': level, 'samples': n, 'consistency': round(frac * 100)}


def anomalies(resources: list[dict], snapshots: dict[str, list[dict]]) -> list[dict]:
    """Latest reading far outside the resource's own baseline. Needs at least 8 readings."""
    out = []
    for r in resources:
        snaps = snapshots.get(r['id'], [])
        if len(snaps) < 8:
            continue
        *prior, last = snaps
        cpus = [s['cpu'] for s in prior]
        mean, std = statistics.fmean(cpus), statistics.pstdev(cpus)
        if last['cpu'] > mean + max(3 * std, 15):
            out.append(dict(resource=r, kind='cpu', detail=f"CPU is {last['cpu']:g}% against a usual {mean:.0f}% over the last {len(prior)} readings."))
        base_cost = statistics.fmean(s['cost'] for s in prior)
        if base_cost > 0 and last['cost'] > base_cost * 1.25:
            out.append(dict(resource=r, kind='cost', detail=f"Monthly cost rose to ${last['cost']:,.0f} from a usual ${base_cost:,.0f}."))
    return out


def fleet_trend(db: Session, limit=60) -> list[dict]:
    """Total monthly run rate per day, from the most recent reading of each resource on that day."""
    snaps = recent(db, limit)
    per_day: dict[str, dict[str, float]] = {}
    for rid, rows in snaps.items():
        for s in rows:
            per_day.setdefault(s['at'].date().isoformat(), {})[rid] = s['cost']
    if not per_day:
        return []
    widest = max(len(v) for v in per_day.values())
    return [{'date': d, 'cost': round(sum(v.values())), 'resources': len(v)} for d, v in sorted(per_day.items()) if len(v) >= widest / 2]


def resource_history(db: Session, resource_id: str, limit=120) -> list[dict]:
    rows = db.scalars(select(MetricSnapshot).where(MetricSnapshot.org_id == org_of(db), MetricSnapshot.resource_id == resource_id)
                      .order_by(MetricSnapshot.captured_at.desc()).limit(limit)).all()
    return [dict(time=_aware(r.captured_at).isoformat(), cpu=r.cpu, memory=r.memory, network=r.network, cost=r.cost) for r in reversed(rows)]
