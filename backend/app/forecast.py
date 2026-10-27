"""Spend forecast: per-resource least-squares trends over the stored metric snapshots (90-day history).
Each resource is trended on its own history, so resources joining or leaving the inventory never fake a jump.
Resources with fewer than 3 daily readings carry no trend (their cost is held flat) and the coverage figure says how much of the
run rate that is. Plain statistics compute every number here; the AI layer only explains them (ai_features.forecast_narrative)."""
import math
from collections import defaultdict
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from .accounts import account_rows
from .history import _aware
from .models import MetricSnapshot, utcnow
from .tenant import org_of
from .services import workspace

HORIZON_DAYS = 30
WINDOW_DAYS = 60
MIN_POINTS = 3


def _fit(series: list[tuple[float, float]]):
    """Slope per day and r-squared of a straight line through (day, cost) points."""
    n = len(series)
    mx, my = sum(x for x, _ in series) / n, sum(y for _, y in series) / n
    sxx = sum((x - mx) ** 2 for x, _ in series)
    slope = sum((x - mx) * (y - my) for x, y in series) / sxx if sxx else 0.0
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for _, y in series)
    ss_res = sum((y - (intercept + slope * x)) ** 2 for x, y in series)
    return slope, (1 - ss_res / ss_tot) if ss_tot else 1.0


def _slope(points: list[tuple[date, float]]) -> float:
    first = points[0][0]
    return _fit([((d - first).days, c) for d, c in points])[0]


def _level(days: int, coverage: float, r2: float) -> str:
    return 'High' if days >= 14 and coverage >= 0.8 and r2 >= 0.7 else 'Medium' if days >= 7 and coverage >= 0.5 else 'Low'


def _readings(db: Session, ids: set[str]) -> dict[str, list[tuple[date, float]]]:
    """Latest reading per day for each resource that is still in the inventory."""
    since = utcnow() - timedelta(days=WINDOW_DAYS)
    rows = db.execute(select(MetricSnapshot.resource_id, MetricSnapshot.captured_at, MetricSnapshot.cost)
                      .where(MetricSnapshot.org_id == org_of(db), MetricSnapshot.captured_at >= since).order_by(MetricSnapshot.captured_at)).all()
    per: dict[str, dict[date, float]] = defaultdict(dict)
    for rid, at, cost in rows:
        if rid in ids:
            per[rid][_aware(at).date()] = cost
    return {rid: sorted(days.items()) for rid, days in per.items()}


def forecast(db: Session) -> dict:
    findings = workspace(db)['findings']
    current = sum(f['cost'] for f in findings)
    history = _readings(db, {f['id'] for f in findings})
    established = {rid: pts for rid, pts in history.items() if len(pts) >= MIN_POINTS}
    slopes = {rid: _slope(pts) for rid, pts in established.items()}
    by_id = {f['id']: f for f in findings}

    # Like-for-like fleet series: only the resources that have a trend, only days when most of them reported.
    per_day: dict[date, float] = defaultdict(float)
    count: dict[date, int] = defaultdict(int)
    for pts in established.values():
        for d, cost in pts:
            per_day[d] += cost
            count[d] += 1
    series = [(d, per_day[d]) for d in sorted(per_day) if count[d] >= len(established) / 2]
    basis_now = sum(by_id[rid]['cost'] for rid in established)
    coverage = basis_now / current if current else 0
    fleet_slope = sum(slopes.values())
    sufficient = bool(established) and len(series) >= MIN_POINTS
    r2 = _fit([((d - series[0][0]).days, c) for d, c in series])[1] if sufficient else 0
    projected = max(0, round(current + fleet_slope * HORIZON_DAYS))

    accounts = []
    for a in account_rows(db, findings):
        if not a['id']:
            continue
        mine = [rid for rid in established if by_id[rid].get('accountId') == a['id']]
        a_slope = sum(slopes[rid] for rid in mine)
        now_cost = a['monthlyCost']
        a_projected = max(0, round(now_cost + a_slope * HORIZON_DAYS))
        a_cover = sum(by_id[rid]['cost'] for rid in mine) / now_cost if now_cost else 0
        budget = a['budgetUsd']
        row = {'id': a['id'], 'name': a['name'], 'provider': a['provider'], 'current': now_cost, 'projected': a_projected,
               'slopePerDay': round(a_slope, 2), 'coveragePct': round(a_cover * 100),
               'confidence': None if not mine else 'High' if a_cover >= 0.8 else 'Medium' if a_cover >= 0.5 else 'Low',
               'budgetUsd': budget, 'utilizationNow': None, 'utilizationProjected': None, 'daysToBudget': None, 'budgetStatus': 'No budget'}
        if budget:
            row['utilizationNow'], row['utilizationProjected'] = round(now_cost / budget * 100), round(a_projected / budget * 100)
            if now_cost >= budget:
                row['budgetStatus'] = 'Over budget now'
            elif a_projected >= budget:
                row['budgetStatus'] = 'Likely to exceed'
            elif a_projected >= budget * 0.9:
                row['budgetStatus'] = 'Close to budget'
            else:
                row['budgetStatus'] = 'On track'
            if a_slope > 0 and now_cost < budget:
                days = math.ceil((budget - now_cost) / a_slope)
                row['daysToBudget'] = days if days <= 180 else None
        accounts.append(row)

    return {
        'horizonDays': HORIZON_DAYS,
        'fleet': {'sufficient': sufficient, 'current': current, 'projected': projected if sufficient else current,
                  'changePct': round((projected - current) / current * 100, 1) if sufficient and current else 0,
                  'slopePerDay': round(fleet_slope, 2), 'readings': len(series),
                  'confidence': _level(len(series), coverage, r2) if sufficient else None,
                  'coveragePct': round(coverage * 100), 'trendedResources': len(established), 'totalResources': len(findings),
                  'basisCurrent': round(basis_now), 'basisProjected': max(0, round(basis_now + fleet_slope * HORIZON_DAYS)),
                  'firstDate': series[0][0].isoformat() if series else None, 'lastDate': series[-1][0].isoformat() if series else None,
                  'series': [{'date': d.isoformat(), 'cost': round(c)} for d, c in series]},
        'accounts': accounts,
        'basis': (f'Each resource is trended on its own daily history (straight line, extended {HORIZON_DAYS} days). {len(established)} of {len(findings)} resources '
                  f'have at least {MIN_POINTS} daily readings, covering {round(coverage * 100)}% of the run rate; the rest are held flat, and new resources are not predicted. '
                  'No planned changes or pending savings are assumed. Cost is on-demand list price, not the invoice.'),
    }
