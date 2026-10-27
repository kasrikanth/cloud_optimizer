"""Approximate public on-demand Linux list prices (USD/month, 730 h, US regions).

Illustrative: used to price collected VMs and to compare clouds. Verify with each provider's calculator.
Every type here is also a valid sizing step for rightsizing: the next smaller size in the same family.
"""

# (provider, family) -> [(vCPU, memory GB, type, USD/month)] ordered small -> large
FAMILIES = {
    ('AWS', 'm5'): [(2, 8, 'm5.large', 70), (4, 16, 'm5.xlarge', 140), (8, 32, 'm5.2xlarge', 280), (16, 64, 'm5.4xlarge', 561), (32, 128, 'm5.8xlarge', 1121)],
    ('AWS', 'm6g'): [(2, 8, 'm6g.large', 56), (4, 16, 'm6g.xlarge', 112), (8, 32, 'm6g.2xlarge', 225), (16, 64, 'm6g.4xlarge', 450)],
    ('AWS', 'r5'): [(2, 16, 'r5.large', 92), (4, 32, 'r5.xlarge', 184), (8, 64, 'r5.2xlarge', 368), (16, 128, 'r5.4xlarge', 736)],
    ('AWS', 'c5'): [(2, 4, 'c5.large', 62), (4, 8, 'c5.xlarge', 124), (8, 16, 'c5.2xlarge', 248), (16, 32, 'c5.4xlarge', 497)],
    ('AWS', 't3'): [(2, 2, 't3.small', 15), (2, 4, 't3.medium', 30), (2, 8, 't3.large', 61), (4, 16, 't3.xlarge', 121), (8, 32, 't3.2xlarge', 243)],
    ('Azure', 'Dsv5'): [(2, 8, 'Standard_D2s_v5', 70), (4, 16, 'Standard_D4s_v5', 140), (8, 32, 'Standard_D8s_v5', 281), (16, 64, 'Standard_D16s_v5', 561), (32, 128, 'Standard_D32s_v5', 1122)],
    ('Azure', 'Dpsv5'): [(2, 8, 'Standard_D2ps_v5', 56), (4, 16, 'Standard_D4ps_v5', 112), (8, 32, 'Standard_D8ps_v5', 225), (16, 64, 'Standard_D16ps_v5', 450)],
    ('Azure', 'Esv5'): [(2, 16, 'Standard_E2s_v5', 92), (4, 32, 'Standard_E4s_v5', 184), (8, 64, 'Standard_E8s_v5', 368), (16, 128, 'Standard_E16s_v5', 736), (32, 256, 'Standard_E32s_v5', 1472)],
    ('Azure', 'Fsv2'): [(2, 4, 'Standard_F2s_v2', 62), (4, 8, 'Standard_F4s_v2', 124), (8, 16, 'Standard_F8s_v2', 248), (16, 32, 'Standard_F16s_v2', 497)],
    ('Azure', 'B'): [(2, 4, 'Standard_B2s', 30), (2, 8, 'Standard_B2ms', 61), (4, 16, 'Standard_B4ms', 121)],
    ('GCP', 'n2-standard'): [(2, 8, 'n2-standard-2', 71), (4, 16, 'n2-standard-4', 142), (8, 32, 'n2-standard-8', 284), (16, 64, 'n2-standard-16', 568), (32, 128, 'n2-standard-32', 1136)],
    ('GCP', 'n2-highmem'): [(2, 16, 'n2-highmem-2', 96), (4, 32, 'n2-highmem-4', 191), (8, 64, 'n2-highmem-8', 383), (16, 128, 'n2-highmem-16', 766)],
    ('GCP', 't2a'): [(2, 8, 't2a-standard-2', 56), (4, 16, 't2a-standard-4', 112), (8, 32, 't2a-standard-8', 225)],
    ('GCP', 'e2-standard'): [(2, 8, 'e2-standard-2', 49), (4, 16, 'e2-standard-4', 98), (8, 32, 'e2-standard-8', 196), (16, 64, 'e2-standard-16', 392)],
}

_LOOKUP = {}
for (_provider, _family), _sizes in FAMILIES.items():
    for _index, (_vcpu, _mem, _type, _price) in enumerate(_sizes):
        _LOOKUP[_type] = dict(provider=_provider, family=_family, vcpu=_vcpu, memoryGb=_mem, monthly=_price, index=_index)


def lookup(instance_type: str):
    return _LOOKUP.get(instance_type)


def smaller(instance_type: str):
    """Next smaller size in the same family as (type, monthly price), or None."""
    info = _LOOKUP.get(instance_type)
    if not info or info['index'] == 0:
        return None
    _, _, name, price = FAMILIES[(info['provider'], info['family'])][info['index'] - 1]
    return name, price


# Equivalent sizes across clouds for the comparison page: (id, family label, vCPU, GB, {provider: (type, USD)})
CLASSES = [
    ('gp-2-8', 'General purpose', 2, 8, {'AWS': ('m5.large', 70), 'Azure': ('Standard_D2s_v5', 70), 'GCP': ('n2-standard-2', 71)}),
    ('gp-4-16', 'General purpose', 4, 16, {'AWS': ('m5.xlarge', 140), 'Azure': ('Standard_D4s_v5', 140), 'GCP': ('n2-standard-4', 142)}),
    ('gp-8-32', 'General purpose', 8, 32, {'AWS': ('m5.2xlarge', 280), 'Azure': ('Standard_D8s_v5', 281), 'GCP': ('n2-standard-8', 284)}),
    ('gp-16-64', 'General purpose', 16, 64, {'AWS': ('m5.4xlarge', 561), 'Azure': ('Standard_D16s_v5', 561), 'GCP': ('n2-standard-16', 568)}),
    ('mem-8-64', 'Memory optimized', 8, 64, {'AWS': ('r5.2xlarge', 368), 'Azure': ('Standard_E8s_v5', 368), 'GCP': ('n2-highmem-8', 383)}),
    ('mem-16-128', 'Memory optimized', 16, 128, {'AWS': ('r5.4xlarge', 736), 'Azure': ('Standard_E16s_v5', 736), 'GCP': ('n2-highmem-16', 766)}),
    ('arm-2-8', 'General purpose · Arm', 2, 8, {'AWS': ('m6g.large', 56), 'Azure': ('Standard_D2ps_v5', 56), 'GCP': ('t2a-standard-2', 56)}),
    ('arm-4-16', 'General purpose · Arm', 4, 16, {'AWS': ('m6g.xlarge', 112), 'Azure': ('Standard_D4ps_v5', 112), 'GCP': ('t2a-standard-4', 112)}),
    ('arm-8-32', 'General purpose · Arm', 8, 32, {'AWS': ('m6g.2xlarge', 225), 'Azure': ('Standard_D8ps_v5', 225), 'GCP': ('t2a-standard-8', 225)}),
]
PRICING_MODELS = [
    {'model': 'On-demand', 'typicalDiscount': '0%', 'note': 'Pay per hour. No commitment. Baseline for every number on this page.'},
    {'model': '1-year commitment', 'typicalDiscount': '30–40%', 'note': 'Reserved Instances, Savings Plans, Reservations or Committed Use. Best for steady workloads.'},
    {'model': '3-year commitment', 'typicalDiscount': '50–60%', 'note': 'Deeper discount, longer lock-in. Needs a stable roadmap.'},
    {'model': 'Spot / preemptible', 'typicalDiscount': 'up to 60–90%', 'note': 'Can be interrupted. Suits batch, CI and fault-tolerant work only.'},
]
