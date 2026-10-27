"""Collector contract. A collector reads one cloud account (read-only) and returns normalized inventory."""
import math
from dataclasses import dataclass, field
from ..pricing import lookup, smaller

OBSERVATION_DAYS = 14


@dataclass
class Collection:
    resources: list[dict]
    warnings: list[str] = field(default_factory=list)
    # resource id -> [{'captured_at': datetime, 'cpu', 'memory', 'network', 'cost'}]; only used to backfill demo history.
    history: dict | None = None
    # Optional extras. None means "not collected this time" (previous data is kept); a list replaces what is stored.
    # spend: [{'month': 'YYYY-MM', 'service': str, 'amount': float}]
    spend: list | None = None
    # assets: [{'service': str, 'asset_id': str, 'name': str, 'region': str, 'type': str, 'state': str, 'detail': dict}]
    # asset_services: the inventory services that were read successfully; only those are replaced.
    assets: list | None = None
    asset_services: set | None = None


class CollectorError(Exception):
    """A failure whose message is safe to show to users (contains no credentials)."""


def percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[rank]


def cost_fields(instance_type: str):
    """(monthly cost, rightsizing target cost) from the bundled price table, or None if the type is unknown."""
    info = lookup(instance_type)
    if not info:
        return None
    step = smaller(instance_type)
    return info['monthly'], (step[1] if step else info['monthly'])


def tag_fields(tags: dict):
    """Environment and criticality come from tags. Untagged resources are treated as Production and critical-safe:
    the rules never suggest stopping a production VM, so a missing tag can only make the tool more cautious."""
    lowered = {str(k).lower(): str(v) for k, v in (tags or {}).items()}
    raw = (lowered.get('environment') or lowered.get('env') or '').lower()
    env = {'prod': 'Production', 'production': 'Production', 'stage': 'Staging', 'staging': 'Staging', 'uat': 'Staging',
           'dev': 'Development', 'development': 'Development', 'test': 'Development', 'qa': 'Development'}.get(raw, 'Production')
    critical = lowered.get('critical', '').lower() in ('true', 'yes', '1')
    owner = lowered.get('owner') or lowered.get('team') or 'Unassigned'
    return env, critical, owner[:160]


class Collector:
    mode = ''

    def test(self, account, credentials: dict) -> str:
        raise NotImplementedError

    def collect(self, account, credentials: dict) -> Collection:
        raise NotImplementedError
