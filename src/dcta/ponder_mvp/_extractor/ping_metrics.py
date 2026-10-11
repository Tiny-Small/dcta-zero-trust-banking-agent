"""Separate Ping multiset metrics. Never awards operation/disposition correctness."""
from collections import Counter,defaultdict
from decimal import Decimal,InvalidOperation
from typing import get_args
from .schema import Role
from .normalization import normalize,canonical
from .candidate_metrics import CONFLICT_PAIRS,distribution,rate
ROLES=get_args(Role)

def evidence_key(e):
    return (e.get("start"),e.get("end"),e.get("text"))
def slot_key(s):
    return (s["role"],*evidence_key(s["evidence"]))
def norm_key(n):
    if not isinstance(n,dict):
        return None
    kind,value=n.get("kind"),n.get("value")
    if kind in {"decimal","percentage","fraction"} and value is not None:
        try:
            number=Decimal(value)
            if not number.is_finite():return ("invalid",None)
            value=canonical(number)
        except (InvalidOperation,TypeError,ValueError):
            return ("invalid",None)
    return (kind,value)
def source_valid(text,slot):
    start,end,quote=evidence_key(slot["evidence"])
    return (slot["role"] in ROLES and isinstance(start,int) and not isinstance(start,bool)
            and isinstance(end,int) and not isinstance(end,bool) and 0<=start<end<=len(text)
            and isinstance(quote,str) and text[start:end]==quote)

def selected_conflicts(slots):
    roles=defaultdict(set)
    for slot in slots:
        roles[evidence_key(slot["evidence"])].add(slot["role"])
    examples=[];pairs=[]
    conflicting=set()
    for a,b in CONFLICT_PAIRS:
        overlap={span for span,rs in roles.items() if a in rs and b in rs}
        union={span for span,rs in roles.items() if a in rs or b in rs}
        pairs.append({"roles":[a,b],"conflicting_span_count":len(overlap),"selected_union_count":len(union),"span_rate":rate(len(overlap),len(union))})
        conflicting|=overlap
    for span in sorted(conflicting,key=repr):
        start,end,text=span
        examples.append({"evidence":{"start":start,"end":end,"text":text},"roles":sorted(roles[span]),
                         "pairs":[list(p) for p in CONFLICT_PAIRS if set(p)<=roles[span]]})
    return {"conflicting_span_count":len(conflicting),"selected_span_count":len(roles),
            "span_rate":rate(len(conflicting),len(roles)),"pairs":pairs,"examples":examples}

def _quality(tp,predicted,gold):
    p=tp/predicted if predicted else None
    r=tp/gold if gold else None
    f=2*tp/(predicted+gold) if predicted+gold else None
    return {"tp":tp,"predicted":predicted,"gold":gold,"precision":p,"recall":r,"f1":f}

def score_ping(example,result):
    gold_slots=[s.model_dump() for op in example.gold.operations for s in op.slots]
    predicted=result["slots"]
    gold=Counter(slot_key(s) for s in gold_slots)
    pred=Counter(slot_key(s) for s in predicted)
    valid_pred=Counter(slot_key(s) for s in predicted if source_valid(example.text,s))
    matched=valid_pred&gold
    tp=sum(matched.values())
    gold_norm=Counter((*slot_key(s),norm_key(s.get("normalized") or normalize(s["role"],s["evidence"]["text"]).model_dump())) for s in gold_slots)
    pred_norm=Counter((*slot_key(s),norm_key(s.get("normalized"))) for s in predicted if source_valid(example.text,s))
    norm_tp=sum((pred_norm&gold_norm).values())
    expected_roles=defaultdict(set)
    for s in gold_slots:expected_roles[evidence_key(s["evidence"])].add(s["role"])
    extra_roles=sum(bool(expected_roles[evidence_key(s["evidence"])]) and s["role"] not in expected_roles[evidence_key(s["evidence"])] for s in predicted)
    conflicts=selected_conflicts(predicted)
    failures=[]
    candidates={c["candidate_id"]:c for c in result.get("candidates",[])}
    inventory={evidence_key(c) for c in candidates.values()}
    pools={r:{evidence_key(candidates[cid]) for cid in ids} for r,ids in result.get("role_pools",{}).items()}
    supply=gold.copy()
    historical=result["policy"]=="historical-gliner"
    for s in predicted:
        k=slot_key(s)
        if source_valid(example.text,s) and supply[k]>0:
            supply[k]-=1
            expected=[x for x in gold_slots if slot_key(x)==k]
            if not any(norm_key(s.get("normalized"))==norm_key(g.get("normalized") or normalize(g["role"],g["evidence"]["text"]).model_dump()) for g in expected):
                failures.append({"class":"normalization_issue","role":s["role"],"evidence":s["evidence"],"direction":"normalization"})
        else:
            conflicted=any(evidence_key(e["evidence"])==evidence_key(s["evidence"]) for e in conflicts["examples"])
            cls="historical_extraction_error" if historical else "deterministic_shortcut_error" if s.get("origin")=="deterministic" else "jev_cross_role_conflict" if conflicted else "jev_wrong_selection"
            failures.append({"class":cls,"role":s["role"],"evidence":s["evidence"],"direction":"extra","origin":s.get("origin")})
    for key,n in (gold-matched).items():
        role,start,end,text=key
        span=(start,end,text)
        status=result.get("role_status",{}).get(role,{})
        if historical:cls="historical_extraction_error"
        elif span not in inventory:cls="candidate_missing"
        elif span not in pools.get(role,set()):cls="candidate_filtered_out"
        elif status.get("origin")=="provider_error":cls=status.get("error_class","provider_timeout/error")
        elif status.get("origin")=="budget_exhausted":cls="budget_exhausted"
        elif result["policy"]=="parser-only":cls="deterministic_shortcut_error"
        elif status.get("origin")=="deterministic":cls="deterministic_shortcut_error"
        elif status.get("reason")=="jev_NONE":cls="jev_none"
        else:cls="jev_wrong_selection"
        failures.append({"class":cls,"role":role,"evidence":{"start":start,"end":end,"text":text},
                         "direction":"missing","multiplicity":n,"termination":status,
                         "note":"Parser-only unresolved-role abstention is not an incorrect emitted shortcut." if result["policy"]=="parser-only" else None})
    # Relation/disposition are preserved as separate unresolved diagnostics, not extraction failures.
    scope=[]
    if len(example.gold.operations)>1:scope.append("unresolved_operation_binding")
    if any(s["state"]!="active" for s in gold_slots):scope.append("unresolved_disposition")
    if any("relational_expression" in c["candidate_types"] for c in candidates.values()):scope.append("outside_ping_scope")
    per_role={r:{"tp":sum(n for k,n in matched.items() if k[0]==r),
                 "predicted":sum(n for k,n in pred.items() if k[0]==r),
                 "gold":sum(n for k,n in gold.items() if k[0]==r)} for r in ROLES}
    unsupported=sum(s.get("normalized") is not None and norm_key(s["normalized"])!=norm_key(normalize(s["role"],s["evidence"]["text"]).model_dump()) for s in predicted if s["role"] in ROLES)
    return {"id":example.id,"text":example.text,"policy":result["policy"],"tp":tp,"predicted":len(predicted),"gold":len(gold_slots),
            "norm_tp":norm_tp,"exact":pred==gold and sum(valid_pred.values())==len(predicted),
            "extra_roles":extra_roles,"invalid_spans":sum(not source_valid(example.text,s) for s in predicted),
            "unsupported_values":unsupported,"covered":any(source_valid(example.text,s) for s in predicted),
            "per_role":per_role,"conflicts":conflicts,"failures":failures,"scope_diagnostics":scope,
            "result":result,"revision":example.revision,"is_final":example.is_final,"turn_id":example.turn_id}

def aggregate_ping(rows):
    tp=sum(r["tp"] for r in rows);pred=sum(r["predicted"] for r in rows);gold=sum(r["gold"] for r in rows)
    ntp=sum(r["norm_tp"] for r in rows)
    normal={**_quality(ntp,pred,gold),"conditional_accuracy":rate(ntp,tp)}
    per_role={role:_quality(*(sum(r["per_role"][role][key] for r in rows) for key in ["tp","predicted","gold"])) for role in ROLES}
    requests=[req for r in rows for req in r["result"]["requests"]]
    decisions=[d for r in rows for d in r["result"].get("decisions",[])]
    statuses=[s for r in rows for s in r["result"]["role_status"].values()]
    origins=Counter(s["origin"] for s in statuses)
    none=sum(d.get("origin")=="none" for d in decisions)
    semantic=sum(r["result"]["semantic_questions"] for r in rows)
    invalid=sum(d.get("error_class")=="provider_contract_error" for d in decisions)
    pairs=[]
    for i,pair in enumerate(CONFLICT_PAIRS):
        parts=[r["conflicts"]["pairs"][i] for r in rows]
        pairs.append({"roles":list(pair),"span_rate":rate(sum(p["conflicting_span_count"] for p in parts),sum(p["selected_union_count"] for p in parts)),
                      "case_rate":rate(sum(p["conflicting_span_count"]>0 for p in parts),len(rows))})
    usage={}
    for field in ["input_tokens","output_tokens","cost"]:
        values=[req["raw_response"]["usage"][field] for req in requests if isinstance(req.get("raw_response"),dict)
                and isinstance(req["raw_response"].get("usage"),dict) and isinstance(req["raw_response"]["usage"].get(field),(int,float))]
        usage[field]={"total":sum(values) if values else None,"available_requests":len(values)}
    timings={k:distribution([r["result"]["timings_ms"][k] for r in rows]) for k in ["candidate_generation","provider_total","end_to_end"]}
    timings["provider_request"]=distribution([req["latency_ms"] for req in requests])
    timings["per_round"]={str(i):distribution([req["latency_ms"] for req in requests if req.get("round")==i]) for i in range(1,5)}
    failcounts=Counter()
    for r in rows:
        for f in r["failures"]:failcounts[f["class"]]+=f.get("multiplicity",1)
    return {"cases":len(rows),"role_span":_quality(tp,pred,gold),"normalization":normal,"per_role":per_role,
            "exact_case_accuracy":rate(sum(r["exact"] for r in rows),len(rows)),
            "coverage":rate(sum(r["covered"] for r in rows),len(rows)),
            "extra_role_rate":rate(sum(r["extra_roles"] for r in rows),pred),
            "extra_prediction_rate":rate(pred-tp,pred),
            "selected_cross_role_conflicts":{"span_rate":rate(sum(r["conflicts"]["conflicting_span_count"] for r in rows),sum(r["conflicts"]["selected_span_count"] for r in rows)),
                "case_rate":rate(sum(r["conflicts"]["conflicting_span_count"]>0 for r in rows),len(rows)),"pairs":pairs,
                "examples":[{"case_id":r["id"],**e} for r in rows for e in r["conflicts"]["examples"]]},
            "abstention":{"jev_NONE_questions":none,"jev_NONE_rate":rate(none,semantic),"empty_pool_roles":origins["empty_pool"],
                "deterministic_abstention_roles":sum(s.get("reason")=="deterministic_abstention" for s in statuses),
                "provider_error_roles":origins["provider_error"],"budget_exhausted_roles":origins["budget_exhausted"],
                "role_terminations":dict(origins),"role_termination_denominator":len(statuses)},
            "unsupported_invalid_choice_rate":rate(invalid,semantic),
            "unsupported_value_rate":rate(sum(r["unsupported_values"] for r in rows),pred),
            "invalid_span_count":sum(r["invalid_spans"] for r in rows),
            "provider_failure_rate":rate(sum(bool(req.get("error_class")) for req in requests),len(requests)),
            "efficiency":{"semantic_questions":distribution([r["result"]["semantic_questions"] for r in rows]),
                "provider_requests":distribution([r["result"]["provider_requests"] for r in rows]),"rounds":distribution([r["result"]["rounds"] for r in rows]),
                "deterministic_only_fraction":rate(sum(r["result"]["provider_requests"]==0 for r in rows),len(rows)),
                "jev_assisted_fraction":rate(sum(r["result"]["provider_requests"]>0 for r in rows),len(rows))},
            "latency_ms":timings,"usage":usage,"failure_counts":dict(failcounts),
            "failure_cases":[{"id":r["id"],"text":r["text"],"failures":r["failures"]} for r in rows if r["failures"]],
            "definitions":{"exact":"Exact role/start/end/text multiset; operation association, state and disposition ignored.",
              "precision":"Correct exact predictions divided by all emitted predictions, including duplicates and invalid source spans.",
              "extra_role":"Prediction assigning an unannotated role to an exact gold evidence span, divided by all predictions. Extra-prediction rate also counts boundary and duplicate errors.",
              "selected_conflict":"Unique selected exact spans with any configured incompatible-role pair / all distinct selected spans. Potential incompatibility, not post-hoc suppression.",
              "parser_only_missing":"Reported as deterministic_shortcut_error with explicit unresolved-role abstention note, not an incorrect emitted shortcut.",
              "historical_failure_classes":"Historical GLiNER errors are marked historical_extraction_error; never attributed to Jev."}}
