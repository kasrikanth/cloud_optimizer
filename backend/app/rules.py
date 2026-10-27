"""One deterministic finding per resource. LLMs do not calculate savings."""
from decimal import Decimal, ROUND_HALF_UP


def rounded(value):
    return int(Decimal(str(value)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def evaluate(r: dict) -> dict:
    if r['days'] < 14 or r['coverage'] < 95 or r['memory'] is None:
        return dict(kind='Review telemetry', action='Collect more data', saving=0, risk='Review',
                    reason='Insufficient telemetry: at least 14 days, 95% coverage, and memory metrics are required.')
    if r['cpu'] < 5 and r['memory'] < 15 and r['network'] < 1 and not r['critical'] and r['env'] != 'Production':
        return dict(kind='Idle resource', action='Stop VM', saving=rounded(r['cost']), risk='Low',
                    reason='Low P95 CPU, memory and network traffic on a non-critical, non-production VM. Confirm ownership, scheduled jobs and dependencies before stopping.')
    if r['cpu'] < 30 and r['memory'] < 40 and r['targetCost'] < r['cost']:
        return dict(kind='Oversized resource', action='Resize VM', saving=rounded(Decimal(str(r['cost'])) - Decimal(str(r['targetCost']))),
                    risk='High' if r['critical'] or r['env'] == 'Production' else 'Medium',
                    reason='P95 CPU below 30% and P95 memory below 40% suggest a smaller configuration. Validate peak jobs, I/O, SKU compatibility and headroom.')
    if r['env'] == 'Development' and not r['critical'] and r['hours'] > 300:
        return dict(kind='After-hours usage', action='Schedule downtime',
                    saving=rounded(Decimal(str(r['cost'])) * (1 - Decimal(220) / Decimal(str(r['hours'])))), risk='Low',
                    reason='Development VM is provisioned continuously. A proposed 220-hour monthly schedule needs owner confirmation; this is not observed inactivity.')
    return dict(kind='Healthy', action='Keep monitoring', saving=0, risk='None',
                reason='No demo rule matched. This does not guarantee optimal sizing.')
