"""Live Azure collector (read-only) using the Azure Resource Manager REST API.

Needs a service principal with the Reader and Monitoring Reader roles on the subscription. Only running VMs are
collected, so a deallocated or deleted VM disappears from the inventory (used to verify "Stop VM" savings).

Method: P95 of hourly averages over 14 days. Memory % is derived from the Azure Monitor "Available Memory Bytes"
metric and the VM size's memory; without guest metrics memory is null and savings are withheld.
"""
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import httpx
from .base import OBSERVATION_DAYS, Collection, Collector, CollectorError, cost_fields, percentile, tag_fields
from ..pricing import lookup

ARM = 'https://management.azure.com'
LOGIN = 'https://login.microsoftonline.com'
METRICS = 'Percentage CPU,Available Memory Bytes,Network In Total,Network Out Total'


class AzureCollector(Collector):
    mode = 'azure'

    def __init__(self, transport=None):
        self._transport = transport

    @contextmanager
    def _session(self, creds):
        with httpx.Client(transport=self._transport, timeout=30, follow_redirects=False) as client:
            response = client.post(f"{LOGIN}/{creds['tenant_id']}/oauth2/v2.0/token", data={
                'grant_type': 'client_credentials', 'client_id': creds['client_id'], 'client_secret': creds['client_secret'],
                'scope': f'{ARM}/.default'})
            if response.status_code != 200:
                raise CollectorError('Azure rejected the service principal credentials. Check the tenant, client ID and secret.')
            client.headers['Authorization'] = 'Bearer ' + response.json()['access_token']
            yield client

    def test(self, account, credentials):
        try:
            with self._session(credentials) as client:
                response = client.get(f'{ARM}/subscriptions/{account.account_ref}', params={'api-version': '2022-12-01'})
        except httpx.HTTPError:
            raise CollectorError('Could not reach Azure. Check the network.')
        if response.status_code in (403, 404):
            raise CollectorError('The service principal cannot read this subscription. Grant it the Reader role.')
        if response.status_code != 200:
            raise CollectorError(f'Azure returned HTTP {response.status_code}.')
        return f"Connected to subscription {response.json().get('displayName', account.account_ref)}."

    def collect(self, account, credentials):
        now = datetime.now(timezone.utc)
        sub, warnings, resources = account.account_ref, [], []
        try:
            with self._session(credentials) as client:
                states = {vm['id'].lower(): _power(vm) for vm in self._pages(client, f'{ARM}/subscriptions/{sub}/providers/Microsoft.Compute/virtualMachines',
                                                                               {'api-version': '2023-09-01', 'statusOnly': 'true'})}
                for vm in self._pages(client, f'{ARM}/subscriptions/{sub}/providers/Microsoft.Compute/virtualMachines', {'api-version': '2023-09-01'}):
                    if states.get(vm['id'].lower()) != 'running':
                        continue
                    row = self._vm(client, account, vm, now, warnings)
                    if row:
                        resources.append(row)
        except httpx.HTTPError:
            raise CollectorError('Could not reach Azure. Check the network.')
        return Collection(resources=resources, warnings=warnings)

    def _pages(self, client, url, params):
        while url:
            response = client.get(url, params=params)
            if response.status_code != 200:
                raise CollectorError(f'Azure returned HTTP {response.status_code} while listing virtual machines. Check the Reader role.')
            body = response.json()
            yield from body.get('value', [])
            url, params = body.get('nextLink'), None

    def _vm(self, client, account, vm, now, warnings):
        size = vm['properties']['hardwareProfile']['vmSize']
        info, prices = lookup(size), cost_fields(size)
        if not prices:
            warnings.append(f"{vm['name']}: VM size {size} is not in the price table and was skipped.")
            return None
        created = vm['properties'].get('timeCreated')
        started = datetime.fromisoformat(created.replace('Z', '+00:00')) if created else now - timedelta(days=OBSERVATION_DAYS)
        observed_hours = max(1.0, min(OBSERVATION_DAYS * 24, (now - started).total_seconds() / 3600))
        response = client.get(f"{ARM}{vm['id']}/providers/microsoft.insights/metrics", params={
            'api-version': '2018-01-01', 'metricnames': METRICS, 'interval': 'PT1H', 'aggregation': 'Average,Total',
            'timespan': f"{(now - timedelta(days=OBSERVATION_DAYS)).strftime('%Y-%m-%dT%H:%M:%SZ')}/{now.strftime('%Y-%m-%dT%H:%M:%SZ')}"})
        series = {}
        if response.status_code == 200:
            for metric in response.json().get('value', []):
                data = (metric.get('timeseries') or [{}])[0].get('data', [])
                key = 'total' if 'Network' in metric['name']['value'] else 'average'
                series[metric['name']['value']] = [d[key] for d in data if key in d]
        else:
            warnings.append(f"{vm['name']}: could not read metrics (HTTP {response.status_code}). Grant Monitoring Reader.")
        cpu = series.get('Percentage CPU', [])
        available = series.get('Available Memory Bytes', [])
        memory = [100 - a / (info['memoryGb'] * 1024 ** 3) * 100 for a in available] if available else []
        net_bytes = sum(series.get('Network In Total', [])) + sum(series.get('Network Out Total', []))
        env, critical, owner = tag_fields(vm.get('tags'))
        return dict(id=_resource_id(vm['id']),
                    name=vm['name'][:160], provider='Azure', accountId=account.id, region=vm['location'], type=size, env=env, owner=owner,
                    cost=prices[0], targetCost=prices[1], cpu=round(percentile(cpu, 95) or 0, 1),
                    memory=round(max(0.0, min(100.0, percentile(memory, 95))), 1) if memory else None,
                    network=round(net_bytes / 1e6 / max(1.0, observed_hours / 24), 2), days=int(min(OBSERVATION_DAYS, observed_hours // 24)),
                    coverage=round(min(100.0, len(cpu) / observed_hours * 100), 1), hours=730, critical=critical)


def _power(vm) -> str:
    for status in vm.get('properties', {}).get('instanceView', {}).get('statuses', []):
        if status.get('code', '').startswith('PowerState/'):
            return status['code'].split('/', 1)[1]
    return 'unknown'


def _resource_id(arm_id: str) -> str:
    short = arm_id.split('/subscriptions/', 1)[-1].replace('/resourceGroups/', '/rg/').replace('/providers/Microsoft.Compute/virtualMachines/', '/vm/')
    return re.sub(r'[^A-Za-z0-9._:/-]', '-', short)[-160:].lstrip('/._:-') or 'vm'
