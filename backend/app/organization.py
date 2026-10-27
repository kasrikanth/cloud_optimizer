"""Organization profile and members. Every organization is isolated; users belong to exactly one."""
import re
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .auth import check_password_strength, hash_password
from .config import get_settings
from .models import Organization, User, utcnow
from .tenant import org_of

EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def get_org(db: Session) -> Organization:
    org = db.get(Organization, org_of(db))
    if org is None:
        raise HTTPException(401, 'Please sign in again.')
    return org


def organization(db: Session) -> dict:
    org, settings = get_org(db), get_settings()
    return {'id': org.id, 'name': org.name, 'updatedBy': org.updated_by, 'createdAt': org.created_at.isoformat(),
            'sessionHours': settings.session_hours, 'syncEnabled': settings.sync_enabled,
            'syncIntervalMinutes': settings.sync_interval_minutes, 'secretsConfigured': bool(settings.secrets_key),
            'llmConfigured': bool(settings.llm_api_key and settings.llm_model)}


def rename(db: Session, name: str, actor: str) -> dict:
    org = get_org(db)
    taken = db.scalar(select(Organization.id).where(func.lower(Organization.name) == name.lower(), Organization.id != org.id))
    if taken:
        raise HTTPException(409, 'An organization with this name already exists.')
    org.name, org.updated_by, org.updated_at = name, actor, utcnow()
    db.flush()
    return organization(db)


def members(db: Session) -> list[dict]:
    rows = db.scalars(select(User).where(User.org_id == org_of(db)).order_by(User.created_at)).all()
    return [{'id': u.id, 'email': u.email, 'name': u.name, 'role': u.role, 'createdAt': u.created_at.isoformat(),
             'lastLoginAt': u.last_login_at.isoformat() if u.last_login_at else None} for u in rows]


def add_member(db: Session, email: str, password: str, name: str, role: str) -> User:
    email = email.lower()
    if not EMAIL.match(email):
        raise HTTPException(422, 'Enter a valid email address.')
    check_password_strength(password)
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, 'This email already has an account.')
    user = User(org_id=org_of(db), email=email, name=name, role=role, password_hash=hash_password(password))
    db.add(user)
    db.flush()
    return user


def remove_member(db: Session, user_id: str, actor_id: str) -> User:
    user = db.get(User, user_id)
    if not user or user.org_id != org_of(db):
        raise HTTPException(404, 'Member not found')
    if user.id == actor_id:
        raise HTTPException(409, 'You cannot remove your own account.')
    if user.role == 'admin' and db.scalar(select(func.count()).select_from(User).where(User.org_id == user.org_id, User.role == 'admin')) <= 1:
        raise HTTPException(409, 'An organization needs at least one admin.')
    db.delete(user)
    db.flush()
    return user


def create_organization(db: Session, org_name: str, email: str, password: str, name: str) -> User:
    """Sign-up: a new organization and its first admin. The name of an old organization that has no users can be claimed."""
    email = email.lower()
    if not EMAIL.match(email):
        raise HTTPException(422, 'Enter a valid email address.')
    check_password_strength(password)
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, 'This email already has an account. Sign in instead.')
    org = db.scalar(select(Organization).where(func.lower(Organization.name) == org_name.lower()))
    if org is not None:
        if db.scalar(select(User.id).where(User.org_id == org.id).limit(1)):
            raise HTTPException(409, 'An organization with this name already exists.')
    else:
        org = Organization(name=org_name, updated_by=email)
        db.add(org)
        db.flush()
    user = User(org_id=org.id, email=email, name=name, role='admin', password_hash=hash_password(password))
    db.add(user)
    db.flush()
    return user
