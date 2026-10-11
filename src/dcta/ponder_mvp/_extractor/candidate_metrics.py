"""Candidate supply, role-filter loss and unsuppressed cross-role ambiguity."""
from collections import Counter
import math
from typing import get_args
from .schema import Role
from .candidate_generation import eligible_candidates

ROLES = get_args(Role)
CONFLICT_PAIRS = (
    ("beneficiary", "source_account"),
    ("beneficiary", "destination_account"),
    ("source_account", "destination_account"),
    ("transfer_amount", "asset_quantity"),
)
CRITICAL_MISS_ROLES = {"beneficiary", "source_account", "destination_account", "transfer_amount"}

def rate(n, d):
    return {"numerator": n, "denominator": d, "value": n / d if d else None}

def distribution(values):
    if not values:
        return {"n": 0, "mean": None, "p50": None, "p95": None, "max": None}
    values = sorted(values)
    return {"n": len(values), "mean": sum(values) / len(values),
            "p50": values[math.ceil(.5 * len(values)) - 1],
            "p95": values[math.ceil(.95 * len(values)) - 1], "max": values[-1]}

def key(candidate):
    return (candidate.start, candidate.end, candidate.text)

def conflict_diagnostics(candidates):
    inventory = {key(c): c for c in candidates}
    eligible = {role: {key(c) for c in eligible_candidates(candidates, role)} for role in ROLES}
    conflicting = set()
    pairs = []
    for a, b in CONFLICT_PAIRS:
        overlap = eligible[a] & eligible[b]
        conflicting |= overlap
        pairs.append({"roles": [a, b], "conflicting_span_count": len(overlap),
                      "eligible_union_count": len(eligible[a] | eligible[b]),
                      "span_rate": rate(len(overlap), len(eligible[a] | eligible[b])),
                      "candidate_ids": [inventory[k].candidate_id for k in sorted(overlap)]})
    return {"candidate_span_count": len(inventory), "conflicting_span_count": len(conflicting),
            "span_rate": rate(len(conflicting), len(inventory)),
            "pairs": pairs, "selected_conflicts": None,
            "note": "Potentially incompatible eligibility, not observed semantic error. No role-selection or exclusivity constraints."}

def score_candidates(example, candidates):
    inventory = {key(c) for c in candidates}
    eligible = {role: {key(c) for c in eligible_candidates(candidates, role)} for role in ROLES}
    # Supply is one per distinct role/evidence key. Different roles may share one span.
    global_supply = Counter((role, *ev) for role in ROLES for ev in inventory)
    filtered_supply = Counter((role, *ev) for role in ROLES for ev in eligible[role])
    per_role = {r: {"gold": 0, "global": 0, "filtered": 0, "eligible_count": len(eligible[r])} for r in ROLES}
    misses = []
    for op in example.gold.operations:
        for slot in op.slots:
            ev = (slot.evidence.start, slot.evidence.end, slot.evidence.text)
            k = (slot.role, *ev)
            g = int(global_supply[k] > 0)
            f = int(filtered_supply[k] > 0)
            global_supply[k] -= g
            filtered_supply[k] -= f
            counts = per_role[slot.role]
            counts["gold"] += 1
            counts["global"] += g
            counts["filtered"] += f
            if not f:
                failure = "candidate_missing" if ev not in inventory else "candidate_multiplicity_shortfall" if not g else "role_filter_removed"
                misses.append({"case_id": example.id, "text": example.text, "operation_id": op.id,
                               "role": slot.role, "evidence": slot.evidence.model_dump(),
                               "state": slot.state, "failure_class": failure,
                               "global_available": bool(g), "filtered_available": bool(f)})
    return {"id": example.id, "text": example.text, "candidate_count": len(inventory),
            "gold_slots": sum(x["gold"] for x in per_role.values()),
            "global_matches": sum(x["global"] for x in per_role.values()),
            "filtered_matches": sum(x["filtered"] for x in per_role.values()),
            "per_role": per_role, "misses": misses, "conflicts": conflict_diagnostics(candidates)}

def aggregate_candidates(rows):
    roles = {}
    for role in ROLES:
        parts = [r["per_role"][role] for r in rows]
        gold = sum(p["gold"] for p in parts)
        roles[role] = {"global_recall": rate(sum(p["global"] for p in parts), gold),
                       "filtered_recall": rate(sum(p["filtered"] for p in parts), gold),
                       "eligible_pool_size": distribution([p["eligible_count"] for p in parts])}
    pairs = []
    for i, pair in enumerate(CONFLICT_PAIRS):
        parts = [r["conflicts"]["pairs"][i] for r in rows]
        count = sum(p["conflicting_span_count"] for p in parts)
        denom = sum(p["eligible_union_count"] for p in parts)
        pairs.append({"roles": list(pair), "span_rate": rate(count, denom),
                      "case_rate": rate(sum(p["conflicting_span_count"] > 0 for p in parts), len(rows))})
    misses = [m for r in rows for m in r["misses"]]
    return {"cases": len(rows),
            "global_recall": rate(sum(r["global_matches"] for r in rows), sum(r["gold_slots"] for r in rows)),
            "filtered_recall": rate(sum(r["filtered_matches"] for r in rows), sum(r["gold_slots"] for r in rows)),
            "per_role": roles, "candidate_counts": distribution([r["candidate_count"] for r in rows]),
            "cross_role_conflicts": {
                "span_rate": rate(sum(r["conflicts"]["conflicting_span_count"] for r in rows), sum(r["candidate_count"] for r in rows)),
                "case_rate": rate(sum(r["conflicts"]["conflicting_span_count"] > 0 for r in rows), len(rows)),
                "pairs": pairs, "selected_conflicts": None,
                "note": "Eligibility only. No selector run; null selected_conflicts means unmeasured, not zero."},
            "misses": misses, "critical_misses": [m for m in misses if m["role"] in CRITICAL_MISS_ROLES],
            "explosion_cases": [{"id": r["id"], "text": r["text"], "candidate_count": r["candidate_count"]}
                                for r in sorted(rows, key=lambda r: (-r["candidate_count"], r["id"]))[:5]],
            "cases_above_40": sum(r["candidate_count"] > 40 for r in rows)}
