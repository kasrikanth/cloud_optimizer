"""Savings ledger: implemented recommendations are verified against later collected data."""
from datetime import timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Recommendation, SavingsEntry, utcnow
from .tenant import org_of

VERIFY_AFTER_DAYS = 14  # an implementation with no visible cost change after this long is marked Not verified


def add_entry(db: Session, rec: Recommendation, resource_data: dict, actor: str):
    db.add(SavingsEntry(resource_id=rec.resource_id, resource_name=resource_data['name'], account_id=resource_data.get('accountId'),
                        action=rec.finding['action'], baseline_cost=resource_data['cost'], expected_saving=rec.finding['saving'],
                        implemented_by=actor))


def verify(db: Session, removed_ids: set[str], incoming: dict[str, dict]):
    """A removed resource saved its full baseline cost; a cheaper replacement saved the difference."""
    now = utcnow()
    for entry in db.scalars(select(SavingsEntry).where(SavingsEntry.org_id == org_of(db), SavingsEntry.status == 'Implemented')).all():
        if entry.resource_id in removed_ids:
            entry.status, entry.verified_saving, entry.verified_at = 'Verified', entry.baseline_cost, now
        elif entry.resource_id in incoming:
            cost = incoming[entry.resource_id]['cost']
            if cost <= entry.baseline_cost * 0.98:
                entry.status, entry.verified_saving, entry.verified_at = 'Verified', round(entry.baseline_cost - cost, 2), now
            else:
                started = entry.implemented_at if entry.implemented_at.tzinfo else entry.implemented_at.replace(tzinfo=timezone.utc)
                if (now - started).days >= VERIFY_AFTER_DAYS:
                    entry.status, entry.verified_at = 'Not verified', now


def summary(db: Session, findings: list[dict]) -> dict:
    entries = db.scalars(select(SavingsEntry).where(SavingsEntry.org_id == org_of(db)).order_by(SavingsEntry.implemented_at.desc()).limit(200)).all()
    verified = [e for e in entries if e.status == 'Verified']
    waiting = [e for e in entries if e.status == 'Implemented']
    return {
        'funnel': {
            'identified': sum(f['saving'] for f in findings if f['status'] == 'Pending'),
            'approved': sum(f['saving'] for f in findings if f['status'] in ('Approved', 'Simulated')),
            'implemented': sum(e.expected_saving for e in waiting),
            'verified': round(sum(e.verified_saving or 0 for e in verified), 2),
        },
        'counts': {'verified': len(verified), 'awaiting': len(waiting), 'notVerified': len([e for e in entries if e.status == 'Not verified'])},
        'annualizedVerified': round(sum(e.verified_saving or 0 for e in verified) * 12),
        'entries': [{'id': e.id, 'resourceId': e.resource_id, 'resource': e.resource_name, 'action': e.action, 'status': e.status,
                     'baselineCost': e.baseline_cost, 'expectedSaving': e.expected_saving, 'verifiedSaving': e.verified_saving,
                     'implementedBy': e.implemented_by, 'implementedAt': e.implemented_at.isoformat(),
                     'verifiedAt': e.verified_at.isoformat() if e.verified_at else None} for e in entries],
    }
