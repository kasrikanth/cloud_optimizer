"""Organization scoping. A database session is bound to one organization; every query filters by it explicitly.

Routes bind the session with `bind(db, org_id)` after authentication. The scheduler binds one account's organization at a
time. New rows of tenant tables get their org_id stamped on flush, so an insert can never land in the wrong tenant or none.
"""
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.orm import Session

ORG_KEY = 'org_id'


def bind(db: Session, org_id: str) -> Session:
    db.info[ORG_KEY] = org_id
    return db


def org_of(db: Session) -> str:
    org = db.info.get(ORG_KEY)
    if not org:
        raise HTTPException(401, 'Please sign in again.')
    return org


@event.listens_for(Session, 'before_flush')
def _stamp_org(session, flush_context, instances):
    org = session.info.get(ORG_KEY)
    for obj in session.new:
        if hasattr(obj, 'org_id') and getattr(obj, 'org_id', None) is None:
            if not org:
                raise RuntimeError(f'{type(obj).__name__} was added without an organization')
            obj.org_id = org
