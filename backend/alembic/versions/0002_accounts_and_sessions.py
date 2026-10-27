"""Organization sessions, cloud accounts and last-seen tracking."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = depends_on = None


def upgrade():
    op.create_table('sessions',
        sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('email', sa.String(160), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('cloud_accounts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('provider', sa.String(10), nullable=False),
        sa.Column('account_ref', sa.String(100), nullable=False),
        sa.Column('region', sa.String(60), nullable=False),
        sa.Column('created_by', sa.String(160), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('provider', 'account_ref', name='uq_cloud_account_ref'))
    op.add_column('resources', sa.Column('seen_at', sa.DateTime(timezone=True), nullable=True))
    op.execute('UPDATE resources SET seen_at = updated_at')


def downgrade():
    op.drop_column('resources', 'seen_at')
    op.drop_table('cloud_accounts')
    op.drop_table('sessions')
