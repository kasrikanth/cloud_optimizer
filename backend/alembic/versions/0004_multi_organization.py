"""Multiple organizations with password sign-in; remove the Boomi outbox and ingestion receipts.

Existing single-organization data is kept: it moves into one organization named after the old organization profile.
That organization has no users yet. Whoever signs up with the same organization name claims it as its first admin.
"""
from uuid import uuid4
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = depends_on = None

TENANT_TABLES = ['cloud_accounts', 'metric_snapshots', 'sync_runs', 'savings_ledger', 'audit_events', 'scans']
PLACEHOLDER = '00000000-0000-0000-0000-000000000000'


def upgrade():
    conn = op.get_bind()
    op.create_table('organizations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(80), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_by', sa.String(160), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(36), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('email', sa.String(160), nullable=False, unique=True),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('password_hash', sa.String(200), nullable=False),
        sa.Column('role', sa.String(10), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True)))
    op.create_index('ix_users_org_id', 'users', ['org_id'])

    # Existing data, if any, becomes one organization.
    has_data = any(conn.execute(sa.text(f'SELECT COUNT(*) FROM {t}')).scalar() for t in ['resources', *TENANT_TABLES])
    legacy = PLACEHOLDER
    if has_data:
        old = conn.execute(sa.text('SELECT name FROM organization ORDER BY id LIMIT 1')).first()
        legacy = str(uuid4())
        now = conn.execute(sa.text('SELECT CURRENT_TIMESTAMP')).scalar()
        conn.execute(sa.text('INSERT INTO organizations (id, name, created_at, updated_by, updated_at) VALUES (:i, :n, :t, :u, :t)'),
                     {'i': legacy, 'n': old[0] if old else 'My organization', 't': now, 'u': 'migration'})

    for table in TENANT_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('org_id', sa.String(36), nullable=False, server_default=legacy))
        with op.batch_alter_table(table) as batch:
            batch.alter_column('org_id', server_default=None)
            batch.create_foreign_key(f'fk_{table}_org', 'organizations', ['org_id'], ['id'], ondelete='CASCADE')
            batch.create_index(f'ix_{table}_org_id', ['org_id'])
    with op.batch_alter_table('cloud_accounts') as batch:
        batch.drop_constraint('uq_cloud_account_ref', type_='unique')
        batch.create_unique_constraint('uq_cloud_account_ref', ['org_id', 'provider', 'account_ref'])
    with op.batch_alter_table('audit_events') as batch:
        batch.alter_column('actor', existing_type=sa.String(100), type_=sa.String(160), existing_nullable=False)

    # Resource ids are now unique per organization (a composite key), so rebuild the two tables and copy the rows.
    resources = conn.execute(sa.text('SELECT id, data, source, updated_at, seen_at FROM resources')).all()
    recommendations = conn.execute(sa.text('SELECT resource_id, finding, status, reviewer, version, generation, updated_at FROM recommendations')).all()
    op.drop_table('recommendations')
    op.drop_table('resources')
    op.create_table('resources',
        sa.Column('org_id', sa.String(36), sa.ForeignKey('organizations.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('source', sa.String(30), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('seen_at', sa.DateTime(timezone=True)))
    op.create_table('recommendations',
        sa.Column('org_id', sa.String(36), primary_key=True),
        sa.Column('resource_id', sa.String(160), primary_key=True),
        sa.Column('finding', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('reviewer', sa.String(80)),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('generation', sa.String(36), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['org_id', 'resource_id'], ['resources.org_id', 'resources.id'], ondelete='CASCADE'))
    if resources:
        res = sa.table('resources', sa.column('org_id'), sa.column('id'), sa.column('data', sa.JSON()), sa.column('source'),
                       sa.column('updated_at'), sa.column('seen_at'))
        rec = sa.table('recommendations', sa.column('org_id'), sa.column('resource_id'), sa.column('finding', sa.JSON()), sa.column('status'),
                       sa.column('reviewer'), sa.column('version'), sa.column('generation'), sa.column('updated_at'))
        op.bulk_insert(res, [{'org_id': legacy, 'id': r.id, 'data': _json(r.data), 'source': r.source, 'updated_at': r.updated_at, 'seen_at': r.seen_at} for r in resources])
        if recommendations:
            op.bulk_insert(rec, [{'org_id': legacy, 'resource_id': r.resource_id, 'finding': _json(r.finding), 'status': r.status, 'reviewer': r.reviewer,
                                  'version': r.version, 'generation': r.generation, 'updated_at': r.updated_at} for r in recommendations])

    # Sessions are tied to users now; everyone signs in again.
    op.drop_table('sessions')
    op.create_table('sessions',
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_sessions_user_id', 'sessions', ['user_id'])

    for table in ['outbox_events', 'ingestion_receipts', 'organization']:
        op.drop_table(table)


def _json(value):
    """Raw SELECT of a JSON column returns text on some drivers; bulk_insert wants the decoded value."""
    import json
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def downgrade():
    raise NotImplementedError('Data from several organizations cannot be merged back into one. Restore a backup instead.')
