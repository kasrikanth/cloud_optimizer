"""Spend by service and a wider read-only inventory (all AWS services the collector can list)."""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = depends_on = None


def upgrade():
    op.create_table('service_costs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(36), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('account_id', sa.String(36), nullable=False),
        sa.Column('month', sa.String(7), nullable=False),
        sa.Column('service', sa.String(120), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_service_costs_org_id', 'service_costs', ['org_id'])
    op.create_index('ix_service_costs_account_month', 'service_costs', ['account_id', 'month'])
    op.create_table('cloud_assets',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(36), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('account_id', sa.String(36), nullable=False),
        sa.Column('service', sa.String(40), nullable=False),
        sa.Column('asset_id', sa.String(300), nullable=False),
        sa.Column('name', sa.String(300), nullable=False),
        sa.Column('region', sa.String(40), nullable=False),
        sa.Column('type', sa.String(80), nullable=False),
        sa.Column('state', sa.String(40), nullable=False),
        sa.Column('detail', sa.JSON(), nullable=False),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_cloud_assets_org_id', 'cloud_assets', ['org_id'])
    op.create_index('ix_cloud_assets_account_service', 'cloud_assets', ['account_id', 'service'])


def downgrade():
    op.drop_table('cloud_assets')
    op.drop_table('service_costs')
