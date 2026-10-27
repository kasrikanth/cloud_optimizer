"""Organization sign-in: email + password. Each user belongs to one organization; a session carries that organization.

Passwords are hashed with scrypt (standard library). Session tokens are random and stored only as a SHA-256 hash.
"""
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from .models import User, UserSession, utcnow

MAX_FAILURES, WINDOW_SECONDS = 5, 600
MIN_PASSWORD = 8
_failures: dict[str, list[float]] = {}
_SCRYPT = dict(n=2 ** 14, r=8, p=1, dklen=32)


@dataclass(frozen=True)
class Principal:
    user_id: str
    org_id: str
    email: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == 'admin'


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${salt.hex()}${hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT).hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split('$')
        if scheme != 'scrypt':
            return False
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
        return hmac.compare_digest(candidate, bytes.fromhex(digest))
    except ValueError:
        return False


# Verified when the email is unknown so a missing account takes as long as a wrong password.
_DUMMY = hash_password('not-a-real-password')


def check_password_strength(password: str):
    if len(password) < MIN_PASSWORD:
        raise HTTPException(422, f'Password must be at least {MIN_PASSWORD} characters.')
    if len(password.encode()) > 200:
        raise HTTPException(422, 'Password is too long.')


def _recent(email: str) -> list[float]:
    cutoff = time.monotonic() - WINDOW_SECONDS
    _failures[email] = [t for t in _failures.get(email, []) if t > cutoff]
    return _failures[email]


def guard_attempts(email: str):
    if len(_recent(email)) >= MAX_FAILURES:
        raise HTTPException(429, 'Too many incorrect attempts. Try again in 10 minutes.')


def record_failure(email: str):
    _recent(email).append(time.monotonic())


def clear_failures(email: str):
    _failures.pop(email, None)


def authenticate(db: Session, email: str, password: str) -> User:
    """Return the user for a correct email + password, or raise 401. Failures are rate-limited per email."""
    guard_attempts(email)
    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(password, user.password_hash if user else _DUMMY)
    if not user or not ok:
        record_failure(email)
        raise HTTPException(401, 'Incorrect email or password.')
    clear_failures(email)
    user.last_login_at = utcnow()
    return user


def open_session(db: Session, user: User, hours: int):
    db.execute(delete(UserSession).where(UserSession.expires_at < utcnow()))
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(hours=hours)
    db.add(UserSession(token_hash=hash_token(token), user_id=user.id, expires_at=expires))
    return token, expires


def principal_for(db: Session, token: str) -> Principal | None:
    row = db.get(UserSession, hash_token(token))
    if not row:
        return None
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=utcnow().tzinfo)
    if expires <= utcnow():
        return None
    user = db.get(User, row.user_id)
    return Principal(user.id, user.org_id, user.email, user.role) if user else None
