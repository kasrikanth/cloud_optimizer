"""Live collectors, metric history, sync runs, savings ledger and organization profile."""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = depends_on = None


def upgrade():
    op.add_column('cloud_accounts', sa.Column('mode', sa.String(10), nullable=False, server_default='import'))
    op.add_column('cloud_accounts', sa.Column('credentials_enc', sa.Text(), nullable=True))
    op.add_column('cloud_accounts', sa.Column('budget_usd', sa.Float(), nullable=True))
    op.add_column('cloud_accounts', sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('cloud_accounts', sa.Column('last_sync_status', sa.String(20), nullable=True))
    op.add_column('cloud_accounts', sa.Column('last_sync_error', sa.String(300), nullable=True))
    op.create_table('metric_snapshots',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('resource_id', sa.String(160), nullable=False),
        sa.Column('account_id', sa.String(36)),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cpu', sa.Float(), nullable=False),
        sa.Column('memory', sa.Float()),
        sa.Column('network', sa.Float(), nullable=False),
        sa.Column('cost', sa.Float(), nullable=False))
    op.create_index('ix_snapshot_resource_time', 'metric_snapshots', ['resource_id', 'captured_at'])
    op.create_index('ix_metric_snapshots_captured_at', 'metric_snapshots', ['captured_at'])
    op.create_table('sync_runs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('account_id', sa.String(36), nullable=False),
        sa.Column('trigger', sa.String(10), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('resources', sa.Integer(), nullable=False),
        sa.Column('message', sa.String(300), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True)))
    op.create_index('ix_sync_runs_account_id', 'sync_runs', ['account_id'])
    op.create_table('savings_ledger',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('resource_id', sa.String(160), nullable=False),
        sa.Column('resource_name', sa.String(160), nullable=False),
        sa.Column('account_id', sa.String(36)),
        sa.Column('action', sa.String(40), nullable=False),
        sa.Column('baseline_cost', sa.Float(), nullable=False),
        sa.Column('expected_saving', sa.Float(), nullable=False),
        sa.Column('verified_saving', sa.Float()),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('implemented_by', sa.String(160), nullable=False),
        sa.Column('implemented_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True)))
    op.create_index('ix_savings_ledger_resource_id', 'savings_ledger', ['resource_id'])
    op.create_table('organization',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('updated_by', sa.String(160), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for name in ['organization', 'savings_ledger', 'sync_runs', 'metric_snapshots']:
        op.drop_table(name)
    for col in ['last_sync_error', 'last_sync_status', 'last_sync_at', 'budget_usd', 'credentials_enc', 'mode']:
        op.drop_column('cloud_accounts', col)
