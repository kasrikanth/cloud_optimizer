"""Synthetic collector. Needs no credentials and makes no network calls.

It generates a believable fleet per account with slowly drifting metrics and 14 days of backfilled history, so every
feature (trends, confidence, anomalies, ledger verification) can be demonstrated without a real cloud account.
Accounts using it are labelled Demo everywhere in the UI.
"""
import hashlib
import random
from datetime import timedelta
from ..models import utcnow
from ..pricing import FAMILIES
from .base import Collection, Collector, cost_fields

FLEETS = {
    'AWS': {'gp': 'm5', 'mem': 'r5'},
    'Azure': {'gp': 'Dsv5', 'mem': 'Esv5'},
    'GCP': {'gp': 'n2-standard', 'mem': 'n2-highmem'},
}
REGION = {'AWS': 'ap-south-1', 'Azure': 'Central India', 'GCP': 'asia-south1'}
OWNERS = ['Platform team', 'Data engineering', 'Payments team', 'Developer experience', 'Search team']
# slug, env, critical, family, size index, (cpu, memory, network MB/day), observed days, coverage %
ARCHETYPES = [
    ('dev-sandbox', 'Development', False, 'gp', 2, (3, 9, 0.3), 30, 99),
    ('staging-api', 'Staging', False, 'gp', 2, (14, 28, 12), 30, 99),
    ('checkout-prod', 'Production', True, 'gp', 2, (46, 58, 60), 30, 99),
    ('reporting-batch', 'Production', False, 'mem', 2, (9, 18, 3), 30, 99),
    ('ci-runner', 'Development', False, 'gp', 1, (22, 30, 14), 30, 98),
    ('etl-new', 'Development', False, 'gp', 1, (5, None, 1), 6, 68),
    ('search-prod', 'Production', False, 'mem', 1, (52, 66, 40), 30, 99),
]
HISTORY_DAYS = 14


def _seed(account) -> int:
    return int(hashlib.sha256(account.id.encode()).hexdigest(), 16) % 1_000_000


def _fleet(account):
    seed = _seed(account)
    family = FAMILIES[(account.provider, FLEETS[account.provider]['gp'])]
    mem_family = FAMILIES[(account.provider, FLEETS[account.provider]['mem'])]
    out = []
    for n, (slug, env, critical, fam, size, base, days, coverage) in enumerate(ARCHETYPES[:5 + seed % 3]):
        sizes = family if fam == 'gp' else mem_family
        _, _, itype, _ = sizes[size]
        out.append(dict(n=n, slug=slug, env=env, critical=critical, type=itype, base=base, days=days, coverage=coverage,
                        owner=OWNERS[(seed + n) % len(OWNERS)], incident=(slug == 'checkout-prod' and seed % 2 == 0)))
    return seed, out


def _metrics(base, rng, incident=False, elevated=False):
    cpu, mem, net = base
    if incident and elevated:
        cpu, mem = 87, 91
    jitter = lambda v: v * (1 + rng.uniform(-0.1, 0.1))
    return (round(max(0.5, jitter(cpu)), 1), None if mem is None else round(min(99, max(1, jitter(mem))), 1), round(max(0.1, jitter(net)), 1))


class DemoCollector(Collector):
    mode = 'demo'

    def test(self, account, credentials):
        return 'Demo mode: synthetic data, no cloud connection needed.'

    def collect(self, account, credentials):
        now = utcnow()
        seed, fleet = _fleet(account)
        bucket = int(now.timestamp() // 1800)
        resources, history = [], {}
        for v in fleet:
            costs = cost_fields(v['type'])
            rid = f'demo-{account.id[-8:]}-{v["n"]}'
            cpu, mem, net = _metrics(v['base'], random.Random(f'{seed}:{v["n"]}:{bucket}'), v['incident'], True)
            resources.append(dict(id=rid, name=f'{v["slug"]}-{v["n"] + 1:02d}', provider=account.provider, accountId=account.id,
                                  region=account.region or REGION[account.provider], type=v['type'], env=v['env'], owner=v['owner'],
                                  cost=costs[0], targetCost=costs[1], cpu=cpu, memory=mem, network=net, days=v['days'],
                                  coverage=v['coverage'], hours=730, critical=v['critical']))
            points = []
            for day in range(HISTORY_DAYS, 0, -1):
                c, m, nt = _metrics(v['base'], random.Random(f'{seed}:{v["n"]}:h{day}'), v['incident'], day <= 1)
                points.append(dict(captured_at=now - timedelta(days=day), cpu=c, memory=m, network=nt, cost=costs[0]))
            history[rid] = points
        return Collection(resources=resources, history=history)
