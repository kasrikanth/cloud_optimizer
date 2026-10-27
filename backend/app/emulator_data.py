"""Static data for the Emulator account modes ("AWS Emulator" and "Azure Emulator").

This file is a SANDBOX. Nothing here comes from a real cloud account, LocalStack or any other emulator process: it is
hand-written data for an imaginary startup, "Northwind Labs", so the optimizer can be shown end to end without waiting two
weeks for real CloudWatch history. Accounts that use it are labelled "Emulator" everywhere in the app and never "Live".

The credentials below are public and intentionally fake. They are the only credentials the emulator modes accept, and they
cannot authenticate to any real cloud. Edit the data freely; the collector (collectors/emulator.py) reads it on every sync.

VM fields: slug, type, env, critical, owner, base = (P95 CPU %, P95 memory % or None, network MB/day), days observed, coverage %.
Types must exist in pricing.py so each VM gets a monthly cost and a smaller target size.
"""

# ---------------------------------------------------------------- credentials
CREDENTIALS = {
    'aws_emu': {
        'access_key_id': 'AKIAEMULATORSANDBOX1',
        'secret_access_key': 'jmgsuR2MZ7tBgONQK7se14/usLxBJZvb7fsXxEg2',
        'regions': 'ap-south-1',
    },
    'azure_emu': {
        'tenant_id': '8f3c2a91-6d47-4b85-9e20-1c7a5d08f632',
        'client_id': 'c4a9e712-3f68-4d02-a5b1-97e6c8302f54',
        'client_secret': 'kQ8~vP3mN7xR2sL9aB5cD0eF6gH1jK4tW8yZ2uV9',
    },
}
DEFAULT_REGION = {'aws_emu': 'ap-south-1', 'azure_emu': 'Central India'}

# ------------------------------------------------------------------------ VMs
VMS = {
    'aws_emu': [
        # slug,             type,          env,           critical, owner,         (cpu, mem, net), days, coverage
        ('web-prod-01',      'm5.xlarge',   'Production',  True,  'Web team',       (52, 61, 80), 14, 99),   # healthy
        ('web-prod-02',      'm5.xlarge',   'Production',  True,  'Web team',       (49, 58, 74), 14, 99),   # healthy
        ('search-prod-01',   'r5.xlarge',   'Production',  False, 'Search team',    (55, 68, 40), 14, 99),   # healthy
        ('api-prod-01',      'c5.xlarge',   'Production',  False, 'Platform team',  (18, 33, 25), 14, 99),   # oversized, high risk (production)
        ('batch-reports-01', 'r5.xlarge',   'Production',  False, 'Data team',      (9, 18, 3),   14, 99),   # oversized
        ('staging-api-01',   'm5.xlarge',   'Staging',     False, 'Platform team',  (12, 24, 6),  14, 99),   # oversized
        ('dev-sandbox-01',   't3.large',    'Development', False, 'Platform team',  (3, 9, 0.3),  14, 99),   # idle
        ('data-etl-01',      'm5.2xlarge',  'Development', False, 'Data team',      (4, 11, 0.8), 14, 98),   # idle
        ('ci-runner-01',     'm5.large',    'Development', False, 'Developer experience', (38, 47, 15), 14, 99),  # after-hours schedule
        ('new-etl-02',       't3.medium',   'Development', False, 'Data team',      (5, None, 1), 6, 68),    # too little telemetry
    ],
    'azure_emu': [
        ('portal-prod-01',   'Standard_D4s_v5', 'Production',  True,  'Web team',       (45, 60, 70), 14, 99),  # healthy
        ('portal-prod-02',   'Standard_D4s_v5', 'Production',  True,  'Web team',       (47, 62, 66), 14, 99),  # healthy
        ('dwh-loader-prod',  'Standard_E4s_v5', 'Production',  False, 'Data team',      (50, 70, 90), 14, 99),  # healthy
        ('analytics-prod-01', 'Standard_E8s_v5', 'Production', False, 'Analytics team', (12, 22, 8),  14, 99),  # oversized, high risk (production)
        ('qa-env-01',        'Standard_D4s_v5', 'Staging',     False, 'QA team',        (14, 26, 8),  14, 99),  # oversized
        ('dev-box-01',       'Standard_D2s_v5', 'Development', False, 'Platform team',  (3, 8, 0.2),  14, 99),  # idle
        ('spark-dev-01',     'Standard_E4s_v5', 'Development', False, 'Analytics team', (4, 12, 0.9), 14, 98),  # idle
        ('dev-tools-01',     'Standard_D4s_v5', 'Development', False, 'Developer experience', (36, 48, 12), 14, 99),  # after-hours schedule
        ('gpu-lab-01',       'Standard_B2ms',   'Development', False, 'Analytics team', (6, None, 1), 5, 60),   # too little telemetry
    ],
}

# ---------------------------------------------------- billed spend by service
# Full-month USD for (two months ago, last month, this month). The current month is scaled to the day of the month.
SPEND = {
    'aws_emu': {
        'Amazon Elastic Compute Cloud - Compute': (1380.0, 1465.0, 1510.0),
        'Amazon Relational Database Service': (420.0, 430.0, 455.0),
        'Amazon Elastic Block Store': (96.4, 101.2, 109.8),
        'Amazon Simple Storage Service': (58.3, 61.7, 66.1),
        'EC2 - Other': (44.9, 47.3, 52.0),
        'Amazon CloudWatch': (31.5, 33.0, 35.2),
        'AWS Lambda': (12.2, 13.9, 15.4),
        'Amazon DynamoDB': (9.8, 10.4, 11.0),
    },
    'azure_emu': {
        'Virtual Machines': (1190.0, 1235.0, 1260.0),
        'Azure SQL Database': (380.0, 390.0, 405.0),
        'Storage': (88.6, 92.1, 97.4),
        'Bandwidth': (41.2, 43.8, 47.5),
        'Azure Monitor': (28.4, 30.1, 31.9),
        'Load Balancer': (24.0, 24.0, 24.0),
        'App Service': (19.6, 21.3, 22.8),
    },
}

# --------------------------------------------- inventory beyond the VMs above
# (service, id, name, type, state, detail). Regions come from the account. "not attached" marks unused disks and IPs.
ASSETS = {
    'aws_emu': [
        ('EBS Volume', 'vol-0e0000000001', 'web-prod-01-root', 'gp3', 'in use', {'sizeGb': 100}),
        ('EBS Volume', 'vol-0e0000000002', 'web-prod-02-root', 'gp3', 'in use', {'sizeGb': 100}),
        ('EBS Volume', 'vol-0e0000000003', 'search-data', 'gp3', 'in use', {'sizeGb': 500}),
        ('EBS Volume', 'vol-0e0000000004', 'old-db-restore', 'gp2', 'not attached', {'sizeGb': 200}),
        ('EBS Volume', 'vol-0e0000000005', 'tmp-export', 'gp2', 'not attached', {'sizeGb': 50}),
        ('Elastic IP', 'eipalloc-0e0001', '13.233.10.21', 'vpc', 'in use', {}),
        ('Elastic IP', 'eipalloc-0e0002', '13.233.10.22', 'vpc', 'in use', {}),
        ('Elastic IP', 'eipalloc-0e0003', '13.233.10.23', 'vpc', 'not attached', {}),
        ('RDS Database', 'orders-db', 'orders-db', 'db.m5.large', 'available', {'engine': 'postgres', 'multiAz': True, 'storageGb': 200}),
        ('RDS Database', 'analytics-db', 'analytics-db', 'db.t3.medium', 'available', {'engine': 'postgres', 'multiAz': False, 'storageGb': 100}),
        ('Load Balancer', 'arn:aws:elasticloadbalancing:ap-south-1:000000000000:loadbalancer/app/shop-alb/0e01', 'shop-alb', 'application', 'active', {}),
        ('S3 Bucket', 'northwind-assets', 'northwind-assets', '', 'active', {}),
        ('S3 Bucket', 'northwind-logs', 'northwind-logs', '', 'active', {}),
        ('S3 Bucket', 'northwind-backups', 'northwind-backups', '', 'active', {}),
        ('Lambda Function', 'thumbnailer', 'thumbnailer', 'python3.12', 'active', {'memoryMb': 512}),
        ('Lambda Function', 'invoice-mailer', 'invoice-mailer', 'nodejs20.x', 'active', {'memoryMb': 256}),
        ('DynamoDB Table', 'sessions', 'sessions', '', 'active', {}),
        ('DynamoDB Table', 'carts', 'carts', '', 'active', {}),
    ],
    'azure_emu': [
        ('Managed Disk', 'disk-0e01', 'portal-prod-01-os', 'Premium_LRS', 'in use', {'sizeGb': 128}),
        ('Managed Disk', 'disk-0e02', 'portal-prod-02-os', 'Premium_LRS', 'in use', {'sizeGb': 128}),
        ('Managed Disk', 'disk-0e03', 'dwh-data', 'Premium_LRS', 'in use', {'sizeGb': 1024}),
        ('Managed Disk', 'disk-0e04', 'orphan-snapshot-disk', 'Standard_LRS', 'not attached', {'sizeGb': 256}),
        ('Public IP', 'pip-0e01', 'portal-lb-ip', 'Standard', 'in use', {}),
        ('Public IP', 'pip-0e02', 'old-vpn-ip', 'Standard', 'not attached', {}),
        ('SQL Database', 'sql-orders', 'orders', 'GP_Gen5_4', 'online', {}),
        ('SQL Database', 'sql-reporting', 'reporting', 'S3', 'online', {}),
        ('Storage Account', 'stnorthwinddata', 'stnorthwinddata', 'StorageV2', 'available', {}),
        ('Storage Account', 'stnorthwindlogs', 'stnorthwindlogs', 'StorageV2', 'available', {}),
        ('Load Balancer', 'lb-portal', 'portal-lb', 'Standard', 'active', {}),
        ('App Service', 'app-docs', 'northwind-docs', 'P1v3', 'running', {}),
    ],
}
