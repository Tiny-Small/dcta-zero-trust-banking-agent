"""Source occurrence certificates, separate from model-facing candidate metadata.

The invariant is generic: a composite cannot equate distinct atomic occurrences.
This first certificate implementation covers numeric transfer/quantity roles only.
No gold, probabilities, normalized values, connectors, or benchmark IDs are used.
"""
import copy
from collections import defaultdict
from .normalization import number

SCALAR_ROLES = frozenset({'transfer_amount', 'asset_quantity'})
VERSION = 'source-occurrence-v1'

def contains(a, b):
    return a['start'] <= b['start'] and b['end'] <= a['end']

def intersects(a, b):
    return max(a['start'], b['start']) < min(a['end'], b['end'])

def order(s):
    e = s['evidence']
    return e['start'], e['end'], s['candidate_id']

def scalar_roots(candidates):
    atoms = [c for c in candidates if 'number' in c['candidate_types']
             and 'numeric_token' in c['generators'] and number(c['text']) is not None]
    words = [c for c in candidates if 'number' in c['candidate_types']
             and 'number_words' in c['generators'] and number(c['text']) is not None]
    maximal = [c for c in words if not any(
        c['candidate_id'] != w['candidate_id'] and contains(w, c)
        and (w['start'], w['end']) != (c['start'], c['end']) for w in words)]
    possible = atoms + maximal
    # Partially overlapping complete parses do not establish unique atoms.
    ambiguous = {c['candidate_id'] for c in possible for d in possible
                 if c['candidate_id'] != d['candidate_id'] and intersects(c, d)}
    roots = [{**copy.deepcopy(c), 'basis': 'licensed_word_scalar' if c in maximal else 'numeric_token'}
             for c in possible if c['candidate_id'] not in ambiguous]
    roots.sort(key=lambda c: (c['start'], c['end'], c['candidate_id']))
    return roots, words, [copy.deepcopy(c) for c in possible if c['candidate_id'] in ambiguous]

def build_families(slots, candidates):
    # Import lazily to keep the original one-argument API as the legacy path.
    from .canonical_diagnostic import build_clusters, ROLES
    roots, words, ambiguities = scalar_roots(candidates)
    side = {'version': VERSION, 'roots': roots, 'ambiguities': ambiguities,
            'compounds': [], 'relations': [], 'families': []}
    groups = []
    for role in ROLES:
        selected = sorted((s for s in slots if s['role'] == role), key=order)
        certified = defaultdict(list)
        legacy = []
        compounds = []
        for s in selected:
            e = s['evidence']
            touching = [r for r in roots if intersects(e, r)] if role in SCALAR_ROLES else []
            if len(touching) > 1:
                complete = all(contains(e, r) for r in touching)
                record = {'slot': copy.deepcopy(s), 'roots': copy.deepcopy(touching),
                          'basis': 'multiple_contained_roots' if complete else 'uncertain_multiple_root_intersection',
                          'selected_child_ids': [], 'retained_in_provenance': True}
                compounds.append(record)
                for r in touching:
                    if contains(e, r):
                        side['relations'].append({'relation': 'CONTAINS_VALUE', 'candidate_id': s['candidate_id'],
                            'role': role, 'root_id': r['candidate_id'], 'root_span': [r['start'], r['end']],
                            'basis': 'source_containment', 'version': VERSION})
                continue
            if len(touching) == 1:
                r = touching[0]
                word_fragment = r['basis'] == 'licensed_word_scalar' and contains(r, e) and any(
                    w['candidate_id'] == s['candidate_id'] for w in words)
                if contains(e, r) or word_fragment:
                    certified[r['candidate_id']].append(s)
                    side['relations'].append({'relation': 'SAME_MENTION_VARIANT', 'candidate_id': s['candidate_id'],
                        'role': role, 'root_id': r['candidate_id'], 'root_span': [r['start'], r['end']],
                        'basis': 'licensed_word_fragment' if word_fragment else 'single_root_containment', 'version': VERSION})
                    continue
            # Uncertified regions never enter certified families, even via overlap.
            legacy.append(s)
        for record in compounds:
            record['selected_child_ids'] = [s['candidate_id'] for r in record['roots']
                for s in certified.get(r['candidate_id'], [])]
        side['compounds'].extend(compounds)
        families = [(ss, 'certified_scalar_occurrence', root_id) for root_id, ss in certified.items()]
        families.extend((g['members'], 'legacy_overlap', None) for g in build_clusters(legacy))
        families.sort(key=lambda g: min(order(s) for s in g[0]))
        for i, (ss, basis, root_id) in enumerate(families, 1):
            group = {'cluster_id': role + '_%02d' % i, 'role': role, 'members': sorted(ss, key=order)}
            groups.append(group)
            side['families'].append({'cluster_id': group['cluster_id'], 'role': role, 'basis': basis,
                'root_id': root_id, 'member_ids': [s['candidate_id'] for s in group['members']]})
    return groups, side
