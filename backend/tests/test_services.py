"""Spend by service and the wider read-only inventory."""
from datetime import datetime, timedelta, timezone
from botocore.exceptions import ClientError
from sqlalchemy import select
from app.collectors import AwsCollector
from app.collectors.base import Collection, Collector
from app.models import CloudAsset, ServiceCost
from conftest import TestSession
from test_platform import vm

CREDS = {'access_key_id': 'AKIAABCDEFGHIJKLMNOP', 'secret_access_key': 'x' * 30, 'regions': ['ap-south-1']}
ACCOUNT = type('A', (), {'id': 'acct-1', 'account_ref': '123412341234'})()
NOW = datetime.now(timezone.utc)


# ------------------------------------------------------------ AWS collector
class Pages:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, **kw):
        return iter(self.pages)


class Client:
    def __init__(self, service, data, denied):
        self.service, self.data, self.denied = service, data, denied

    def _check(self):
        if self.service in self.denied:
            raise ClientError({'Error': {'Code': 'AccessDenied', 'Message': 'no'}}, 'Op')

    def get_paginator(self, operation):
        self._check()
        return Pages(self.data.get(operation, [{}]))

    def describe_addresses(self):
        self._check()
        return {'Addresses': self.data['addresses']}

    def list_buckets(self):
        self._check()
        return {'Buckets': self.data['buckets']}

    def get_cost_and_usage(self, **kw):
        self._check()
        self.data['ce_calls'].append(kw)
        return self.data['ce'].pop(0)

    def get_metric_data(self, **kw):
        return {'MetricDataResults': [{'Id': q['Id'], 'Values': [2.0] * 300 if q['Id'][0] in 'cio' else []} for q in kw['MetricDataQueries']]}

    def get_caller_identity(self):
        return {'Account': '123412341234'}


def factory(denied=()):
    month = NOW.strftime('%Y-%m')
    data = {
        'describe_instances': [{'Reservations': [{'Instances': [{'InstanceId': 'i-1', 'InstanceType': 'm5.large', 'LaunchTime': NOW - timedelta(days=30),
                                                                    'Tags': [{'Key': 'Name', 'Value': 'web'}]}]}]}],
        'describe_volumes': [{'Volumes': [{'VolumeId': 'vol-1', 'Size': 100, 'VolumeType': 'gp3', 'Attachments': [{'InstanceId': 'i-1'}]},
                                          {'VolumeId': 'vol-2', 'Size': 500, 'VolumeType': 'gp2', 'Attachments': []}]}],
        'addresses': [{'AllocationId': 'eipalloc-1', 'PublicIp': '3.3.3.3', 'Domain': 'vpc'}],
        'describe_db_instances': [{'DBInstances': [{'DBInstanceIdentifier': 'orders-db', 'DBInstanceClass': 'db.m5.large', 'Engine': 'postgres',
                                                    'DBInstanceStatus': 'available', 'MultiAZ': True, 'AllocatedStorage': 200}]}],
        'describe_load_balancers': [{'LoadBalancers': [{'LoadBalancerArn': 'arn:aws:elasticloadbalancing:x:lb/app/shop/1', 'LoadBalancerName': 'shop',
                                                       'Type': 'application', 'State': {'Code': 'active'}}]}],
        'list_functions': [{'Functions': [{'FunctionName': 'thumbnailer', 'Runtime': 'python3.12', 'MemorySize': 512}]}],
        'list_tables': [{'TableNames': ['sessions', 'carts']}],
        'buckets': [{'Name': 'acme-assets', 'CreationDate': NOW}],
        'ce_calls': [],
        'ce': [{'ResultsByTime': [
            {'TimePeriod': {'Start': (NOW.replace(day=1) - timedelta(days=1)).strftime('%Y-%m') + '-01'},
             'Groups': [{'Keys': ['Amazon Elastic Compute Cloud - Compute'], 'Metrics': {'UnblendedCost': {'Amount': '1200.456'}}}]},
            {'TimePeriod': {'Start': month + '-01'},
             'Groups': [{'Keys': ['Amazon Elastic Compute Cloud - Compute'], 'Metrics': {'UnblendedCost': {'Amount': '400.1'}}},
                        {'Keys': ['Amazon Relational Database Service'], 'Metrics': {'UnblendedCost': {'Amount': '250'}}},
                        {'Keys': ['Tax'], 'Metrics': {'UnblendedCost': {'Amount': '0.0'}}}]}]}],
    }
    return (lambda service, **kw: Client(service, data, set(denied))), data


def test_aws_collector_reads_spend_and_inventory_across_services():
    make, data = factory()
    result = AwsCollector(client_factory=make).collect(ACCOUNT, CREDS)
    assert len(result.resources) == 1 and result.warnings == []
    assert [(r['month'], r['service'], r['amount']) for r in result.spend] == [
        ((NOW.replace(day=1) - timedelta(days=1)).strftime('%Y-%m'), 'Amazon Elastic Compute Cloud - Compute', 1200.46),
        (NOW.strftime('%Y-%m'), 'Amazon Elastic Compute Cloud - Compute', 400.1),
        (NOW.strftime('%Y-%m'), 'Amazon Relational Database Service', 250.0)]  # the $0 Tax line is dropped
    by_service = {}
    for a in result.assets:
        by_service.setdefault(a['service'], []).append(a)
    assert {s: len(v) for s, v in by_service.items()} == {'EC2 Instance': 1, 'EBS Volume': 2, 'Elastic IP': 1, 'RDS Database': 1,
                                                          'Load Balancer': 1, 'Lambda Function': 1, 'DynamoDB Table': 2, 'S3 Bucket': 1}
    assert sorted(a['state'] for a in by_service['EBS Volume']) == ['in use', 'not attached']
    assert by_service['Elastic IP'][0]['state'] == 'not attached' and by_service['RDS Database'][0]['detail']['multiAz'] is True
    assert result.asset_services == set(by_service)
    # Cost Explorer is queried once, for the last three months, grouped by service, in us-east-1.
    assert len(data['ce_calls']) == 1 and data['ce_calls'][0]['GroupBy'][0]['Key'] == 'SERVICE'
    start = datetime.fromisoformat(data['ce_calls'][0]['TimePeriod']['Start'])
    assert start.day == 1 and 55 <= (NOW.replace(tzinfo=None) - start).days <= 92


def test_missing_optional_permissions_only_warn_and_never_break_the_vm_sync():
    make, _ = factory(denied={'ce', 'rds', 's3'})
    result = AwsCollector(client_factory=make).collect(ACCOUNT, CREDS)
    assert len(result.resources) == 1  # the VM analysis is unaffected
    assert result.spend is None  # not collected: previously stored spend must be kept
    assert 'RDS Database' not in result.asset_services and 'S3 Bucket' not in result.asset_services
    assert 'EBS Volume' in result.asset_services
    text = ' '.join(result.warnings)
    assert 'ce:GetCostAndUsage' in text and 'rds:DescribeDBInstances' in text and 's3:ListAllMyBuckets' in text


# -------------------------------------------------------- stored and served
class Extras(Collector):
    mode = 'demo'

    def __init__(self, spend=None, assets=None, covered=None):
        self.spend, self.assets, self.covered = spend, assets, covered

    def test(self, account, credentials):
        return 'ok'

    def collect(self, account, credentials):
        return Collection(resources=[{**vm(), 'accountId': account.id}], spend=self.spend, assets=self.assets, asset_services=self.covered)


def asset(service, asset_id, state='in use', **kw):
    return {'service': service, 'asset_id': asset_id, 'name': asset_id, 'region': 'ap-south-1', 'type': '', 'state': state, 'detail': {}, **kw}


def spend(month, **amounts):
    return [{'month': month, 'service': s, 'amount': a} for s, a in amounts.items()]


def setup(client, headers, monkeypatch, collector, name='Acct One', ref='111122223333'):
    holder = {'collector': collector}
    monkeypatch.setattr('app.sync.get_collector', lambda mode: holder['collector'] if mode == 'demo' else None)
    body = client.post('/api/accounts', headers=headers, json={'name': name, 'provider': 'AWS', 'account_ref': ref, 'mode': 'demo'}).json()
    return body['id'], holder


def test_overview_summarises_spend_and_inventory(client, headers, monkeypatch):
    this, last = NOW.strftime('%Y-%m'), (NOW.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
    account_id, _ = setup(client, headers, monkeypatch, Extras(
        spend=spend(last, EC2=1000, RDS=200) + spend(this, EC2=600, RDS=300, S3=100),
        assets=[asset('EBS Volume', 'vol-1'), asset('EBS Volume', 'vol-2', 'not attached'), asset('RDS Database', 'db-1')],
        covered={'EBS Volume', 'RDS Database'}))
    data = client.get('/api/cloud-services', headers=headers).json()
    assert data['months'] == [last, this] and data['currentMonth'] == this and data['monthToDate'] is True
    assert data['spend']['total'] == {last: 1200.0, this: 1000.0}
    top = data['spend']['byService']
    assert [r['service'] for r in top] == ['EC2', 'RDS', 'S3'] and top[0]['share'] == 60.0 and top[0]['amounts'][last] == 1000.0
    assert data['spend']['byAccount'] == [{'id': account_id, 'name': 'Acct One', 'amounts': {last: 1200.0, this: 1000.0}}]
    assert data['inventory']['total'] == 3
    assert {r['service']: (r['count'], r['notAttached']) for r in data['inventory']['byService']} == {'EBS Volume': (2, 1), 'RDS Database': (1, 0)}
    assert data['accounts'][0]['hasSpend'] is True and data['accounts'][0]['assetCount'] == 3 and data['assetsTruncated'] is False
    assert {a['assetId'] for a in data['assets']} == {'vol-1', 'vol-2', 'db-1'} and data['assets'][0]['account'] == 'Acct One'


def test_resync_replaces_data_but_keeps_what_was_not_collected(client, headers, monkeypatch):
    this = NOW.strftime('%Y-%m')
    account_id, holder = setup(client, headers, monkeypatch, Extras(
        spend=spend(this, EC2=500), assets=[asset('EBS Volume', 'vol-1'), asset('RDS Database', 'db-1')], covered={'EBS Volume', 'RDS Database'}))
    # Next sync: spend could not be read (None) and RDS was denied, EBS changed.
    holder['collector'] = Extras(spend=None, assets=[asset('EBS Volume', 'vol-9')], covered={'EBS Volume'})
    assert client.post(f'/api/accounts/{account_id}/sync', headers=headers).json()['status'] == 'Success'
    data = client.get('/api/cloud-services', headers=headers).json()
    assert data['spend']['total'] == {this: 500.0}  # kept
    assert {a['assetId'] for a in data['assets']} == {'vol-9', 'db-1'}  # EBS replaced, RDS kept
    # A sync that did read spend replaces it; an empty list means "nothing billed".
    holder['collector'] = Extras(spend=spend(this, EC2=50), assets=[], covered={'RDS Database'})
    client.post(f'/api/accounts/{account_id}/sync', headers=headers)
    data = client.get('/api/cloud-services', headers=headers).json()
    assert data['spend']['total'] == {this: 50.0} and {a['assetId'] for a in data['assets']} == {'vol-9'}


def test_overview_is_per_organization_and_cleaned_up_with_the_account(client, headers, other_headers, monkeypatch):
    this = NOW.strftime('%Y-%m')
    account_id, _ = setup(client, headers, monkeypatch, Extras(spend=spend(this, EC2=500), assets=[asset('EBS Volume', 'vol-1')], covered={'EBS Volume'}))
    other = client.get('/api/cloud-services', headers=other_headers).json()
    assert other['spend']['byService'] == [] and other['assets'] == [] and other['inventory']['total'] == 0 and other['accounts'] == []
    assert client.get('/api/cloud-services').status_code == 401
    assert client.delete(f'/api/accounts/{account_id}', headers=other_headers).status_code == 404  # not theirs
    assert client.delete(f'/api/accounts/{account_id}', headers=headers).status_code == 200
    with TestSession() as db:
        assert db.scalars(select(ServiceCost)).all() == [] and db.scalars(select(CloudAsset)).all() == []
    assert client.get('/api/cloud-services', headers=headers).json()['inventory']['total'] == 0


def test_demo_and_import_accounts_without_extras_show_empty(client, headers):
    client.post('/api/accounts', headers=headers, json={'name': 'Plain demo', 'provider': 'AWS', 'account_ref': '555566667777', 'mode': 'demo'})
    data = client.get('/api/cloud-services', headers=headers).json()
    assert data['currentMonth'] is None and data['spend']['byService'] == [] and data['collectedAt'] is None
    assert data['accounts'][0]['hasSpend'] is False and data['accounts'][0]['assetCount'] == 0
