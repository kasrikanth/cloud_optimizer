"""Emulator collectors: serve the static sandbox data in emulator_data.py through the normal collector interface.

No network calls are made and no real cloud, LocalStack or other emulator process is contacted. The only accepted
credentials are the fake ones published in emulator_data.py. Results flow through the same ingest, rules, history and
ledger code as a live account, and the account is labelled "Emulator" in the app.
"""
import calendar
import hmac
import random
from datetime import timedelta
from .. import emulator_data as data
from ..models import utcnow
from .base import Collection, Collector, CollectorError, cost_fields

HISTORY_DAYS = 14
SERVICE_LABEL = {'aws_emu': 'EC2 Instance', 'azure_emu': 'Virtual Machine'}
CLOUD = {'aws_emu': ('AWS', 'AWS Emulator'), 'azure_emu': ('Azure', 'Azure Emulator')}


def _jitter(base, rng, amount=0.06):
    cpu, mem, net = base
    j = lambda v: v * (1 + rng.uniform(-amount, amount))
    return (round(max(0.5, j(cpu)), 1), None if mem is None else round(min(99, max(1, j(mem))), 1), round(max(0.1, j(net)), 2))


class EmulatorCollector(Collector):
    def __init__(self, mode):
        self.mode = mode
        self.provider, self.label = CLOUD[mode]

    def _check(self, credentials):
        expected = data.CREDENTIALS[self.mode]
        for key, value in expected.items():
            if key == 'regions':
                continue
            if not isinstance(credentials.get(key), str) or not hmac.compare_digest(credentials[key].encode(), value.encode()):
                raise CollectorError(f'These are not the {self.label} credentials. Use the sandbox credentials shown when adding the account.')

    def test(self, account, credentials):
        self._check(credentials)
        return f'Connected to the {self.label}. This is sandbox data from the app, not a real {self.provider} account.'

    def collect(self, account, credentials):
        self._check(credentials)
        now = utcnow()
        region = account.region or data.DEFAULT_REGION[self.mode]
        bucket = int(now.timestamp() // 1800)
        resources, history, assets = [], {}, []
        for n, (slug, vm_type, env, critical, owner, base, days, coverage) in enumerate(data.VMS[self.mode]):
            costs = cost_fields(vm_type)
            if not costs:
                raise CollectorError(f'Emulator data error: instance type {vm_type} is not in the price table.')
            rid = f'emu-{account.id[-8:]}-{n + 1:02d}'
            cpu, mem, net = _jitter(base, random.Random(f'{rid}:{bucket}'), 0.03)
            resources.append(dict(id=rid, name=slug, provider=self.provider, accountId=account.id, region=region, type=vm_type, env=env,
                                  owner=owner, cost=costs[0], targetCost=costs[1], cpu=cpu, memory=mem, network=net, days=days,
                                  coverage=coverage, hours=730, critical=critical))
            history[rid] = [dict(captured_at=now - timedelta(days=day), cost=costs[0], **dict(zip(('cpu', 'memory', 'network'),
                            _jitter(base, random.Random(f'{rid}:h{day}')))))
                            for day in range(min(days, HISTORY_DAYS), 0, -1)]
            vm_id = f'i-0e{n + 1:015x}' if self.mode == 'aws_emu' else f'/subscriptions/{account.account_ref}/resourceGroups/northwind/providers/Microsoft.Compute/virtualMachines/{slug}'
            assets.append(dict(service=SERVICE_LABEL[self.mode], asset_id=vm_id, name=slug, region=region, type=vm_type, state='running',
                               detail={'environment': env, 'owner': owner}))
        for service, asset_id, name, kind, state, detail in data.ASSETS[self.mode]:
            assets.append(dict(service=service, asset_id=asset_id, name=name, region='' if service == 'S3 Bucket' else region, type=kind,
                               state=state, detail=detail))
        return Collection(resources=resources, history=history, spend=self._spend(now), assets=assets,
                          asset_services={a['service'] for a in assets})

    def _spend(self, now):
        first = now.replace(day=1)
        last_month = first - timedelta(days=1)
        two_ago = last_month.replace(day=1) - timedelta(days=1)
        fraction = min(1.0, now.day / calendar.monthrange(now.year, now.month)[1])
        rows = []
        for service, (older, previous, current) in data.SPEND[self.mode].items():
            for month, amount in ((two_ago, older), (last_month, previous), (now, current * fraction)):
                rows.append({'month': month.strftime('%Y-%m'), 'service': service, 'amount': round(amount, 2)})
        return rows
