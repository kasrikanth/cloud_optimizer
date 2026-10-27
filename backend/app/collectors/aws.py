"""Live AWS collector (read-only): EC2 inventory + CloudWatch metrics, plus spend by service and a wider inventory.

Required IAM permissions (all read-only): ec2:DescribeInstances, cloudwatch:GetMetricData, sts:GetCallerIdentity.
Optional, each one enables a feature and a missing one only produces a warning: ce:GetCostAndUsage (spend by service),
ec2:DescribeVolumes, ec2:DescribeAddresses, rds:DescribeDBInstances, elasticloadbalancing:DescribeLoadBalancers,
lambda:ListFunctions, dynamodb:ListTables, s3:ListAllMyBuckets (inventory).
Only running instances are analysed for savings. A stopped or terminated instance simply disappears from the inventory,
which is how an implemented "Stop VM" recommendation is later verified.

Method: P95 of hourly averages over the last 14 days. Memory comes from the CloudWatch agent (CWAgent
mem_used_percent); without the agent memory is null and savings are withheld. Network is MB/day (in + out).
"""
from datetime import datetime, timedelta, timezone
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from .base import OBSERVATION_DAYS, Collection, Collector, CollectorError, cost_fields, percentile, tag_fields

BATCH = 100  # instances per GetMetricData call (4 queries each, API limit 500)
MAX_ASSETS = 5000


class AwsCollector(Collector):
    mode = 'aws'

    def __init__(self, client_factory=None):
        self._factory = client_factory or boto3.client

    def _client(self, service, creds, region=None):
        return self._factory(service, aws_access_key_id=creds['access_key_id'], aws_secret_access_key=creds['secret_access_key'],
                             region_name=region or creds['regions'][0])

    def test(self, account, credentials):
        try:
            identity = self._client('sts', credentials).get_caller_identity()
        except (ClientError, BotoCoreError) as exc:
            raise CollectorError(_message(exc))
        if identity.get('Account') != account.account_ref:
            raise CollectorError(f"These credentials belong to AWS account {identity.get('Account')}, but this account is {account.account_ref}.")
        return f"Connected to AWS account {identity['Account']}."

    def collect(self, account, credentials):
        now = datetime.now(timezone.utc)
        resources, warnings, assets, failed = [], [], [], set()
        regions = credentials['regions']
        try:
            for region in regions:
                rows, instances = self._region(account, credentials, region, now, warnings)
                resources += rows
                assets += [_asset('EC2 Instance', i['InstanceId'], _name(i.get('Tags'), i['InstanceId']), region, i.get('InstanceType', ''), 'running',
                                  {'launched': i['LaunchTime'].isoformat()} if i.get('LaunchTime') else {}) for i in instances]
        except (ClientError, BotoCoreError) as exc:
            raise CollectorError(_message(exc))
        for index, region in enumerate(regions):
            self._inventory(credentials, region, index == 0, assets, failed, warnings)
        covered = set(SERVICES) - failed
        if len(assets) > MAX_ASSETS:
            warnings.append(f'More than {MAX_ASSETS} resources found; only the first {MAX_ASSETS} are listed.')
            assets = assets[:MAX_ASSETS]
        spend = self._guard(warnings, 'Spend by service', 'ce:GetCostAndUsage', lambda: self._spend(credentials, now))
        return Collection(resources=resources, warnings=warnings, spend=spend, assets=assets, asset_services=covered)

    @staticmethod
    def _guard(warnings, label, action, fn, failed=None):
        """Optional features must never break the VM sync: a failure becomes a warning and the call returns None."""
        try:
            return fn()
        except (ClientError, BotoCoreError) as exc:
            note = f'{label}: {_message(exc)} It needs {action}.'
        except Exception as exc:  # noqa: BLE001 -- unexpected shapes from AWS must not fail the whole sync
            note = f'{label}: could not be read ({type(exc).__name__}).'
        if failed is not None:
            failed.add(label)
        if note not in warnings:
            warnings.append(note)
        return None

    def _spend(self, creds, now):
        ce = self._client('ce', creds, 'us-east-1')  # Cost Explorer is a global service served from us-east-1
        first = now.replace(day=1)
        start = ((first - timedelta(days=1)).replace(day=1) - timedelta(days=1)).replace(day=1)  # two months back
        kwargs = dict(TimePeriod={'Start': start.date().isoformat(), 'End': (now + timedelta(days=1)).date().isoformat()},
                      Granularity='MONTHLY', Metrics=['UnblendedCost'], GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}])
        rows = []
        while True:
            response = ce.get_cost_and_usage(**kwargs)
            for period in response.get('ResultsByTime', []):
                month = period['TimePeriod']['Start'][:7]
                for group in period.get('Groups', []):
                    amount = float(group['Metrics']['UnblendedCost']['Amount'])
                    if abs(amount) >= 0.005:
                        rows.append({'month': month, 'service': group['Keys'][0][:120], 'amount': round(amount, 2)})
            token = response.get('NextPageToken')
            if not token:
                return rows
            kwargs['NextPageToken'] = token

    def _inventory(self, creds, region, first_region, assets, failed, warnings):
        ec2, rds, elb = self._client('ec2', creds, region), self._client('rds', creds, region), self._client('elbv2', creds, region)
        lam, ddb = self._client('lambda', creds, region), self._client('dynamodb', creds, region)

        def pages(client, operation, key, **kw):
            for page in client.get_paginator(operation).paginate(**kw):
                yield from page.get(key, [])

        def volumes():
            return [_asset('EBS Volume', v['VolumeId'], _name(v.get('Tags'), v['VolumeId']), region, v.get('VolumeType', ''),
                           'in use' if v.get('Attachments') else 'not attached',
                           {'sizeGb': v.get('Size'), 'attachedTo': [a.get('InstanceId') for a in v.get('Attachments', [])]})
                    for v in pages(ec2, 'describe_volumes', 'Volumes')]

        def addresses():
            return [_asset('Elastic IP', a.get('AllocationId') or a['PublicIp'], a.get('PublicIp', ''), region, 'vpc' if a.get('Domain') == 'vpc' else 'ec2-classic',
                           'in use' if a.get('AssociationId') else 'not attached', {})
                    for a in ec2.describe_addresses().get('Addresses', [])]

        def databases():
            return [_asset('RDS Database', d['DBInstanceIdentifier'], d['DBInstanceIdentifier'], region, d.get('DBInstanceClass', ''), d.get('DBInstanceStatus', ''),
                           {'engine': d.get('Engine'), 'multiAz': d.get('MultiAZ'), 'storageGb': d.get('AllocatedStorage')})
                    for d in pages(rds, 'describe_db_instances', 'DBInstances')]

        def balancers():
            return [_asset('Load Balancer', b['LoadBalancerArn'], b.get('LoadBalancerName', ''), region, b.get('Type', ''), (b.get('State') or {}).get('Code', ''), {})
                    for b in pages(elb, 'describe_load_balancers', 'LoadBalancers')]

        def functions():
            return [_asset('Lambda Function', f['FunctionName'], f['FunctionName'], region, f.get('Runtime', ''), 'active',
                           {'memoryMb': f.get('MemorySize')}) for f in pages(lam, 'list_functions', 'Functions')]

        def tables():
            return [_asset('DynamoDB Table', t, t, region, '', 'active', {}) for t in pages(ddb, 'list_tables', 'TableNames')]

        def buckets():
            s3 = self._client('s3', creds, region)
            return [_asset('S3 Bucket', b['Name'], b['Name'], '', '', 'active', {'created': b['CreationDate'].isoformat() if b.get('CreationDate') else None})
                    for b in s3.list_buckets().get('Buckets', [])]

        steps = [('EBS Volume', 'ec2:DescribeVolumes', volumes), ('Elastic IP', 'ec2:DescribeAddresses', addresses),
                 ('RDS Database', 'rds:DescribeDBInstances', databases), ('Load Balancer', 'elasticloadbalancing:DescribeLoadBalancers', balancers),
                 ('Lambda Function', 'lambda:ListFunctions', functions), ('DynamoDB Table', 'dynamodb:ListTables', tables)]
        if first_region:  # S3 bucket names are global, so list them once
            steps.append(('S3 Bucket', 's3:ListAllMyBuckets', buckets))
        for label, action, fn in steps:
            found = self._guard(warnings, label, action, fn, failed)
            if found:
                assets += found

    def _region(self, account, creds, region, now, warnings):
        ec2, cloudwatch = self._client('ec2', creds, region), self._client('cloudwatch', creds, region)
        instances = []
        for page in ec2.get_paginator('describe_instances').paginate(Filters=[{'Name': 'instance-state-name', 'Values': ['running']}]):
            for reservation in page['Reservations']:
                instances += reservation['Instances']
        out = []
        for start in range(0, len(instances), BATCH):
            chunk = instances[start:start + BATCH]
            metrics = self._metrics(cloudwatch, chunk, now)
            for index, inst in enumerate(chunk):
                itype = inst['InstanceType']
                prices = cost_fields(itype)
                if not prices:
                    warnings.append(f"{inst['InstanceId']}: instance type {itype} is not in the price table and was skipped.")
                    continue
                tags = {t['Key']: t['Value'] for t in inst.get('Tags', [])}
                env, critical, owner = tag_fields(tags)
                observed_hours = max(1.0, min(OBSERVATION_DAYS * 24, (now - inst['LaunchTime']).total_seconds() / 3600))
                days = int(min(OBSERVATION_DAYS, observed_hours // 24))
                cpu, mem = metrics.get(f'c{index}', []), metrics.get(f'm{index}', [])
                net_bytes = sum(metrics.get(f'i{index}', [])) + sum(metrics.get(f'o{index}', []))
                if not cpu:
                    warnings.append(f"{inst['InstanceId']}: no CloudWatch CPU data yet; reported with zero coverage.")
                out.append(dict(
                    id=inst['InstanceId'], name=(tags.get('Name') or inst['InstanceId'])[:160], provider='AWS', accountId=account.id,
                    region=region, type=itype, env=env, owner=owner, cost=prices[0], targetCost=prices[1],
                    cpu=round(percentile(cpu, 95) or 0, 1), memory=round(percentile(mem, 95), 1) if mem else None,
                    network=round(net_bytes / 1e6 / max(1.0, observed_hours / 24), 2), days=days,
                    coverage=round(min(100.0, len(cpu) / observed_hours * 100), 1), hours=730, critical=critical))
        return out, instances

    def _metrics(self, cloudwatch, chunk, now):
        queries = []
        for i, inst in enumerate(chunk):
            dim = [{'Name': 'InstanceId', 'Value': inst['InstanceId']}]
            for key, namespace, name, stat in (('c', 'AWS/EC2', 'CPUUtilization', 'Average'), ('m', 'CWAgent', 'mem_used_percent', 'Average'),
                                               ('i', 'AWS/EC2', 'NetworkIn', 'Sum'), ('o', 'AWS/EC2', 'NetworkOut', 'Sum')):
                queries.append({'Id': f'{key}{i}', 'ReturnData': True, 'MetricStat': {
                    'Metric': {'Namespace': namespace, 'MetricName': name, 'Dimensions': dim}, 'Period': 3600, 'Stat': stat}})
        values, token = {}, None
        while True:
            kwargs = dict(MetricDataQueries=queries, StartTime=now - timedelta(days=OBSERVATION_DAYS), EndTime=now)
            if token:
                kwargs['NextToken'] = token
            response = cloudwatch.get_metric_data(**kwargs)
            for result in response.get('MetricDataResults', []):
                values.setdefault(result['Id'], []).extend(result.get('Values', []))
            token = response.get('NextToken')
            if not token:
                return values


SERVICES = ('EC2 Instance', 'EBS Volume', 'Elastic IP', 'RDS Database', 'Load Balancer', 'Lambda Function', 'DynamoDB Table', 'S3 Bucket')


def _name(tags, fallback):
    for tag in tags or []:
        if tag.get('Key') == 'Name' and tag.get('Value'):
            return tag['Value'][:300]
    return fallback


def _asset(service, asset_id, name, region, kind, state, detail):
    return {'service': service, 'asset_id': asset_id[:300], 'name': (name or asset_id)[:300], 'region': region, 'type': kind or '', 'state': state or '', 'detail': detail}


def _message(exc) -> str:
    if isinstance(exc, ClientError):
        error = exc.response.get('Error', {})
        return f"AWS rejected the request: {error.get('Code', 'Error')}. Check the IAM permissions and that the access key is active."
    return 'Could not reach AWS. Check the network and the region names.'
