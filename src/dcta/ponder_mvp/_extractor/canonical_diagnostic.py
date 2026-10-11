"""Frozen saved semantic candidates -> same-role canonical span -> reference scope."""
import copy
import json
import time
from typing import get_args
from .schema import Role, Example, ExtractionResult, Operation
from .ping_metrics import score_ping
from .providers.decisions import parse_choices
ROLES=get_args(Role)
RESOLVED_MODEL="typesafe/jev-1.13-20260917"

CANONICAL_COMMON=(
 "Which supplied candidate is the canonical evidence span for this semantic role? "
 "Select the smallest COMPLETE span expressing the semantic value required by the role. "
 "Exclude surrounding words belonging to other separately modeled slots or optional framing, "
 "while retaining words necessary to identify the value. "
 "Choose exactly one candidate ID from this same-role overlap cluster, or NONE only if no member is a valid canonical representation. "
 "Use the full utterance and exact supplied spans. Do not reconstruct text, invent offsets, merge spans, or select a candidate from another cluster. "
 "Separate non-overlapping mentions must remain separate. "
 "Do not determine operation grouping, lifecycle, authorization, bank grounding or execution."
)
CANONICAL_ROLE_CRITERIA={
 "transfer_amount":"Select the numeric amount expression. Exclude a separately represented currency code/sign when possible. Do not select a larger money span if an exact numeric amount candidate independently expresses the slot.",
 "currency":"Select the literal currency sign/code span; do not infer a code for a bare sign.",
 "source_account":"Select the complete account-identifying phrase for the user-owned source account. Avoid incomplete fragments and optional possessive/determiner material when the remaining phrase still completely identifies the account. Do not reduce to a generic head when a more identifying complete phrase exists.",
 "destination_account":"Select the complete account-identifying phrase for the user-owned destination account. Avoid incomplete fragments and optional possessive/determiner material when the remaining phrase still completely identifies the account. Do not reduce to a generic head when a more identifying complete phrase exists.",
 "beneficiary":"Select the complete person/payee mention. Avoid partial-name fragments when a complete name candidate exists.",
 "asset_quantity":"Select the quantity expression itself, excluding words that identify a separate instrument or unit type.",
 "asset":"Select the instrument/security identifier itself. Exclude generic unit/type words such as shares or units when a more identifying asset name/ticker candidate exists. Retain such words only when genuinely part of the asset identifier.",
 "percentage":"Select the complete literal percentage expression.",
 "fraction":"Select the complete literal fraction expression.",
 "dependent_amount":"Select the complete dependency expression, not merely its inner numeric or fractional fragment.",
 "payment_reference":"Select the literal content supplied as reference/memo. Do not select descriptive surrounding words unless those words themselves are actually the supplied reference value."
}
SCOPE_COMMON=(
 "What is the scope status of the INNER candidate given the selected enclosing data-container span? "
 "Choose exactly one supplied scope status. Use the full utterance and supplied outer/inner roles, evidence and metadata. "
 "Determine whether the inner evidence independently participates in the transaction instruction or is only content of the enclosing payment-reference/memo value. "
 "This is a scope decision, not deletion of source provenance. "
 "Do not determine operation grouping, active/rejected/superseded lifecycle, authorization, bank grounding or execution."
)
SCOPE_CRITERIA={
 "TOP_LEVEL_SLOT":"The inner candidate independently participates in the user's actual transaction instruction outside the meaning of the enclosing data field.",
 "NESTED_DATA":"The inner candidate is content inside the enclosing memo/reference/data value and must not be promoted as a top-level transaction slot.",
 "NONE":"The candidate should not survive as a semantic slot."
}

def overlap(a,b):
 return max(a["start"],b["start"])<min(a["end"],b["end"])

def build_clusters(slots, candidates=None):
 if candidates is not None:
  from .canonical_components import build_families
  return build_families(slots,candidates)[0]
 groups=[]
 for role in ROLES:
  ordered=sorted((s for s in slots if s["role"]==role),key=lambda s:(s["evidence"]["start"],s["evidence"]["end"],s["candidate_id"]))
  remaining=set(range(len(ordered)))
  index=0
  while remaining:
   first=min(remaining);remaining.remove(first)
   component={first};queue=[first]
   while queue:
    current=queue.pop()
    neighbors=[j for j in sorted(remaining) if overlap(ordered[current]["evidence"],ordered[j]["evidence"])]
    remaining.difference_update(neighbors);component.update(neighbors);queue.extend(neighbors)
   index+=1
   groups.append({"cluster_id":role+"_%02d"%index,"role":role,"members":[ordered[j] for j in sorted(component)]})
 return groups

def candidate_metadata(row,slot):
 c=next(c for c in row["result"]["candidates"] if c["candidate_id"]==slot["candidate_id"])
 e=slot["evidence"]
 if (c["text"],c["start"],c["end"])!=(e["text"],e["start"],e["end"]) or row["text"][c["start"]:c["end"]]!=c["text"]:
  raise ValueError("Saved source-span regression before provider call")
 return copy.deepcopy(c)

def canonical_request(row, *, families=None):
 clusters=families if families is not None else build_clusters(row["result"]["slots"],row["result"]["candidates"])
 active=[g for g in clusters if len(g["members"])>1]
 state={"transcript":row["text"],"canonical_clusters":[{"cluster_id":g["cluster_id"],"role":g["role"],
  "candidates":[candidate_metadata(row,s) for s in g["members"]]} for g in active]}
 questions={g["cluster_id"]:{"type":"choice","instructions":CANONICAL_COMMON+" Role: "+CANONICAL_ROLE_CRITERIA[g["role"]]+" Cluster ID: "+g["cluster_id"],
  "criteria":{**{s["candidate_id"]:json.dumps(candidate_metadata(row,s),ensure_ascii=False,separators=(",",":")) for s in g["members"]},
   "NONE":"No supplied candidate is a valid canonical representation of this role."}} for g in active}
 return clusters,state,questions

def bounded_request(state,questions,provider):
 if not questions:return [],{}, {},0
 response=provider.decide(state=copy.deepcopy(state),questions=copy.deepcopy(questions))
 envelope=response.get("raw_response")
 valid,errors=parse_choices(envelope,questions)
 unsupported=0
 if isinstance(envelope,dict) and isinstance(envelope.get("answers"),dict):
  unsupported=sum(isinstance(a,dict) and isinstance(a.get("choice"),str) and a["choice"] not in questions[k]["criteria"]
   for k,a in envelope["answers"].items() if k in questions)
 if response.get("http_status")!=200:
  category="provider_timeout_error" if response.get("transport_error_type") in {"TimeoutError","URLError","OSError"} else "provider_contract_error"
  valid={};errors={k:category for k in questions}
 elif not isinstance(envelope,dict) or envelope.get("model")!=RESOLVED_MODEL or envelope.get("provider")!="TypeSafe":
  valid={};errors={k:"provider_contract_error" for k in questions}
 return [response],valid,errors,unsupported

def canonicalize(row,*,provider):
 started=time.perf_counter()
 from .canonical_components import build_families
 clusters,structural_provenance=build_families(row["result"]["slots"],row["result"]["candidates"])
 clusters,state,questions=canonical_request(row,families=clusters)
 requests,answers,errors,unsupported=bounded_request(state,questions,provider)
 selected=set();decisions=[]
 for g in clusters:
  if len(g["members"])==1:
   selected.add(g["members"][0]["candidate_id"])
   continue
  answer=answers.get(g["cluster_id"])
  choice=answer["choice"] if answer else None
  error=errors.get(g["cluster_id"])
  decisions.append({"cluster_id":g["cluster_id"],"role":g["role"],"member_ids":[s["candidate_id"] for s in g["members"]],
   "answer":answer,"error_class":error,"selected_candidate_id":choice if choice!="NONE" else None})
  if not error and choice!="NONE":selected.add(choice)
 return {"stage":"canonical","id":row["id"],"text":row["text"],"slots":copy.deepcopy([s for s in row["result"]["slots"] if s["candidate_id"] in selected]),
  "structural_provenance":structural_provenance,
  "clusters":clusters,"cluster_decisions":decisions,"requests":requests,
  "semantic_questions":len(questions),"http_requests":len(requests),"unsupported_choices":unsupported,
  "stopped":bool(errors),"timings_ms":{"stage_wall":(time.perf_counter()-started)*1000,"provider_total":sum(r["latency_ms"] for r in requests)}}

def scope_request(row,canonical):
 slots=canonical["slots"]
 pairs=[]
 for outer in slots:
  if outer["role"]!="payment_reference":continue
  for inner in slots:
   if inner["role"]=="payment_reference" or inner["candidate_id"]==outer["candidate_id"]:continue
   a,b=outer["evidence"],inner["evidence"]
   if a["start"]<=b["start"] and a["end"]>=b["end"]:
    pairs.append({"pair_id":"scope_"+outer["candidate_id"]+"_"+inner["candidate_id"],
     "outer":{"role":outer["role"],"candidate":candidate_metadata(row,outer)},
     "inner":{"role":inner["role"],"candidate":candidate_metadata(row,inner)}})
 state={"transcript":row["text"],"containment_pairs":pairs}
 questions={p["pair_id"]:{"type":"choice","instructions":SCOPE_COMMON+" Pair ID: "+p["pair_id"],
  "criteria":copy.deepcopy(SCOPE_CRITERIA)} for p in pairs}
 return pairs,state,questions

def resolve_scope(row,canonical,*,provider):
 started=time.perf_counter()
 pairs,state,questions=scope_request(row,canonical)
 requests,answers,errors,unsupported=bounded_request(state,questions,provider)
 suppress=set();relations=[]
 for pair in pairs:
  answer=answers.get(pair["pair_id"]);status=answer["choice"] if answer else None;error=errors.get(pair["pair_id"])
  if error or status in {"NESTED_DATA","NONE"}:suppress.add(pair["inner"]["candidate"]["candidate_id"])
  relations.append({**pair,"status":status,"answer":answer,"error_class":error,
   "top_level_survives":not error and status=="TOP_LEVEL_SLOT","retained_in_provenance":True})
 return {"stage":"scope","id":row["id"],"text":row["text"],"slots":copy.deepcopy([s for s in canonical["slots"] if s["candidate_id"] not in suppress]),
  "scope_relations":relations,"requests":requests,"semantic_questions":len(questions),
  "http_requests":len(requests),"unsupported_choices":unsupported,"stopped":bool(errors),
  "timings_ms":{"stage_wall":(time.perf_counter()-started)*1000,"provider_total":sum(r["latency_ms"] for r in requests)}}

def score_stage(row,stage):
 example=Example(id=row["id"],text=row["text"],template_family="existing_frozen_smoke",
  gold=ExtractionResult(operations=[Operation(id="unassociated-diagnostic",slots=row["gold_role_spans"])]))
 # Legacy metric consumes this view; no new annotation, normalization or validation behavior.
 metric_result={"policy":"canonical-diagnostic","text":row["text"],"slots":stage["slots"],
  "candidates":row["result"]["candidates"],"role_pools":row["result"]["role_pools"],
  "role_status":{},"requests":stage.get("requests",[]),"decisions":[],
  "semantic_questions":stage.get("semantic_questions",0),"provider_requests":stage.get("http_requests",0)}
 score=score_ping(example,metric_result)
 score["gold_role_spans"]=row["gold_role_spans"]
 score["stage_result"]=stage
 return score
