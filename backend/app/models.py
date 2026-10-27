from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import JSON, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def utcnow():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid4())


class Organization(Base):
    __tablename__ = 'organizations'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(160), default='')
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    """A person who signs in with email + password. Each user belongs to exactly one organization."""
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    email: Mapped[str] = mapped_column(String(160), unique=True)
    name: Mapped[str] = mapped_column(String(80), default='')
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(10), default='member')  # admin | member
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Resource(Base):
    __tablename__ = 'resources'
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), primary_key=True)
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(30), default='import')
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Last time any collector/import reported this resource, even if nothing changed.
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=utcnow)


class UserSession(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CloudAccount(Base):
    __tablename__ = 'cloud_accounts'
    __table_args__ = (UniqueConstraint('org_id', 'provider', 'account_ref', name='uq_cloud_account_ref'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(10))
    account_ref: Mapped[str] = mapped_column(String(100))
    region: Mapped[str] = mapped_column(String(60), default='')
    created_by: Mapped[str] = mapped_column(String(160), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # How inventory arrives: demo (synthetic), aws/azure (live read-only collector), import (JSON).
    mode: Mapped[str] = mapped_column(String(10), default='import')
    credentials_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(String(300), nullable=True)


class MetricSnapshot(Base):
    __tablename__ = 'metric_snapshots'
    __table_args__ = (Index('ix_snapshot_resource_time', 'resource_id', 'captured_at'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    resource_id: Mapped[str] = mapped_column(String(160))
    account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    cpu: Mapped[float] = mapped_column(Float)
    memory: Mapped[float | None] = mapped_column(Float, nullable=True)
    network: Mapped[float] = mapped_column(Float, default=0)
    cost: Mapped[float] = mapped_column(Float)


class SyncRun(Base):
    __tablename__ = 'sync_runs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    account_id: Mapped[str] = mapped_column(String(36), index=True)
    trigger: Mapped[str] = mapped_column(String(10), default='manual')
    status: Mapped[str] = mapped_column(String(20))
    resources: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(String(300), default='')
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SavingsEntry(Base):
    """Closes the loop: an implemented recommendation is later verified against collected data."""
    __tablename__ = 'savings_ledger'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    resource_id: Mapped[str] = mapped_column(String(160), index=True)
    resource_name: Mapped[str] = mapped_column(String(160))
    account_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    baseline_cost: Mapped[float] = mapped_column(Float)
    expected_saving: Mapped[float] = mapped_column(Float)
    verified_saving: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='Implemented')  # Implemented | Verified | Not verified
    implemented_by: Mapped[str] = mapped_column(String(160), default='')
    implemented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Recommendation(Base):
    __tablename__ = 'recommendations'
    __table_args__ = (ForeignKeyConstraint(['org_id', 'resource_id'], ['resources.org_id', 'resources.id'], ondelete='CASCADE'),)
    org_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    finding: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default='Pending')
    reviewer: Mapped[str | None] = mapped_column(String(80), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    generation: Mapped[str] = mapped_column(String(36), default=uid)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    title: Mapped[str] = mapped_column(String(160))
    detail: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(160), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Scan(Base):
    __tablename__ = 'scans'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    count: Mapped[int] = mapped_column(Integer)
    findings: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ServiceCost(Base):
    """Billed cost of one cloud service for one month, as reported by the provider's cost API."""
    __tablename__ = 'service_costs'
    __table_args__ = (Index('ix_service_costs_account_month', 'account_id', 'month'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    account_id: Mapped[str] = mapped_column(String(36))
    month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    service: Mapped[str] = mapped_column(String(120))
    amount: Mapped[float] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CloudAsset(Base):
    """One resource of any service found in an account (read-only inventory; no savings analysis)."""
    __tablename__ = 'cloud_assets'
    __table_args__ = (Index('ix_cloud_assets_account_service', 'account_id', 'service'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    account_id: Mapped[str] = mapped_column(String(36))
    service: Mapped[str] = mapped_column(String(40))
    asset_id: Mapped[str] = mapped_column(String(300))
    name: Mapped[str] = mapped_column(String(300), default='')
    region: Mapped[str] = mapped_column(String(40), default='')
    type: Mapped[str] = mapped_column(String(80), default='')
    state: Mapped[str] = mapped_column(String(40), default='')
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
