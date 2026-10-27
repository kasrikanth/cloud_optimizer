"""Initial inventory, recommendations, audit and integration tables."""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = depends_on = None


def upgrade():
    op.create_table('resources',
        sa.Column('id', sa.String(160), primary_key=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('source', sa.String(30), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('recommendations',
        sa.Column('resource_id', sa.String(160), sa.ForeignKey('resources.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('finding', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('reviewer', sa.String(80)),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('generation', sa.String(36), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('audit_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('title', sa.String(160), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False),
        sa.Column('actor', sa.String(100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('scans',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('findings', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('outbox_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('last_error', sa.String(200)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('ingestion_receipts',
        sa.Column('key', sa.String(100), primary_key=True),
        sa.Column('checksum', sa.String(64), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    for name in ['ingestion_receipts', 'outbox_events', 'scans', 'audit_events', 'recommendations', 'resources']:
        op.drop_table(name)
