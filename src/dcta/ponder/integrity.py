"""Representation checks only: no words, allocation or discourse classification."""
import hashlib
from collections import Counter
from .base import ROLE_FIELDS
from .ir import IntegrityReport, CompilationIssue
from .relations import *
from .serialization import content_sha256


def all_mentions(snapshot):
    return snapshot.semantic_mentions + (snapshot.prior_context.semantic_mentions if snapshot.prior_context else ())

def all_anchors(snapshot):
    return snapshot.relational_anchors + (snapshot.prior_context.relational_anchors if snapshot.prior_context else ())

def all_scopes(snapshot):
    return snapshot.ping_projection + (snapshot.prior_context.ping_projection if snapshot.prior_context else ())

def frame_ids(claim):
    if isinstance(claim, (ReplacesClaim, RejectsClaim)):
        return (claim.target.frame_id,) + ((claim.replacement_frame_id,) if isinstance(claim,ReplacesClaim) else ())
    if isinstance(claim, (SharedFieldClaim, CoordinatedClaim)): return claim.frame_ids
    if isinstance(claim,AlternativeClaim): return tuple(f for b in claim.branches for f in b.frame_ids)
    return (claim.frame_id,) if hasattr(claim,"frame_id") else ()

def cyclic_nodes(graph):
    """Kahn remainder includes cyclic nodes and dependents, all unsafe to apply."""
    pending={k:set(v) for k,v in graph.items()}
    while pending:
        ready={k for k,v in pending.items() if not v.intersection(pending)}
        if not ready: return set(pending)
        pending={k:v-ready for k,v in pending.items() if k not in ready}
    return set()

def check_integrity(snapshot, bundle) -> IntegrityReport:
    issues=[]; blocked=set(); affected=set(); global_error=False
    def issue(category, ids=(), claim=None, *, severity="ERROR", global_=False):
        nonlocal global_error
        issues.append(CompilationIssue(category=category,affected_ids=tuple(sorted(set(ids))),support_ids=(claim.id,) if claim else (),severity=severity))
        if claim: blocked.add(claim.id)
        if severity=="ERROR" and claim: affected.update(frame_ids(claim))
        global_error |= global_
    if bundle.snapshot_sha256 != content_sha256(snapshot): issue("SNAPSHOT_MISMATCH",global_=True)
    prior=snapshot.prior_context
    sources=(snapshot.current_source,) + (prior.sources if prior else ())
    mm=all_mentions(snapshot); aa=all_anchors(snapshot); scopes=all_scopes(snapshot)
    mentions={m.id:m for m in mm}; anchors={a.id:a for a in aa}; source_map={s.id:s for s in sources}
    for table in (sources,mm,aa):
        for id,n in Counter(x.id for x in table).items():
            if not id or n>1: issue("DUPLICATE_ID",(id,),global_=True)
    if set(mentions)&set(anchors): issue("ID_NAMESPACE_CONFLICT",tuple(set(mentions)&set(anchors)),global_=True)
    for s in sources:
        if hashlib.sha256(s.text.encode()).hexdigest()!=s.text_sha256: issue("INVALID_SOURCE_HASH",(s.id,),global_=True)
    for x in mm+aa:
        e=x.evidence;s=source_map.get(e.source_id)
        if not s or not 0<=e.start<e.end<=len(s.text) or s.text[e.start:e.end]!=e.text: issue("INVALID_SOURCE_SPAN",(x.id,),global_=True)
    for projection in scopes:
        if projection.mention_id not in mentions or (projection.parent_mention_id and projection.parent_mention_id not in mentions): issue("UNKNOWN_ID",(projection.mention_id,),global_=True)
    if len({x.mention_id for x in scopes})!=len(scopes): issue("DUPLICATE_SCOPE",global_=True)
    parents={x.mention_id:{x.parent_mention_id} for x in scopes if x.parent_mention_id}
    if cyclic_nodes(parents): issue("CYCLIC_RELATION",tuple(cyclic_nodes(parents)),global_=True)
    for retained in snapshot.retained_compounds:
        if retained.mention_id not in mentions: issue("UNKNOWN_ID",(retained.mention_id,),global_=True)
    claims=bundle.claims; claim_map={c.id:c for c in claims}
    frames={c.frame_id:c for c in claims if isinstance(c,FrameClaim)}
    prior_versions=prior.versions if prior else ()
    known_frames=set(frames)|{v.frame_id for v in prior_versions}
    known_versions={(c.frame_id,c.version_id) for c in claims if isinstance(c,FrameClaim)}|{(v.frame_id,v.version_id) for v in prior_versions}|{(c.replacement_frame_id,c.replacement_version_id) for c in claims if isinstance(c,ReplacesClaim)}
    for id,n in Counter(c.id for c in claims).items():
        if not id or n>1: issue("DUPLICATE_ID",(id,),global_=True)
    for id,n in Counter(c.frame_id for c in claims if isinstance(c,FrameClaim)).items():
        if n>1: issue("DUPLICATE_FRAME",(id,),global_=True)
    for id,n in Counter(v.id for v in prior_versions).items():
        if not id or n>1: issue("DUPLICATE_PRIOR_VERSION",(id,),global_=True)
    for key,n in Counter((v.frame_id,v.version_id) for v in prior_versions).items():
        if n>1: issue("DUPLICATE_PRIOR_VERSION",key,global_=True)
    initial_versions={(c.frame_id,c.version_id) for c in claims if isinstance(c,FrameClaim)}|{(v.frame_id,v.version_id) for v in prior_versions}
    creators={}
    for c in claims:
        if isinstance(c,ReplacesClaim):creators.setdefault((c.replacement_frame_id,c.replacement_version_id),[]).append(c)
    prior_keys={(v.frame_id,v.version_id) for v in prior_versions}
    for key,cc in creators.items():
        if key in prior_keys:
            for c in cc:issue("VERSION_ID_REUSE",key,c)
        if len(cc)>1:
            for c in cc:issue("DUPLICATE_VERSION_CREATOR",key,c)
    for v in prior_versions:
        if len({f.field for f in v.fields})!=len(v.fields): issue("DUPLICATE_PRIOR_FIELD",(v.id,),global_=True)
        for field in v.fields:
            for id in field.mention_ids:
                if id not in mentions or mentions[id].role not in ROLE_FIELDS[field.field]: issue("INVALID_PRIOR_FIELD",(v.id,id),global_=True)
    prior_ids={m.id for m in prior.semantic_mentions} if prior else set()
    reference_carriers={c.carrier_mention_id for c in claims if isinstance(c,RefersToClaim)}
    def mention(id,c,field=None):
        if id in anchors: issue("ANCHOR_AS_FIELD",(id,),c);return
        if id not in mentions: issue("UNKNOWN_ID",(id,),c);return
        if field and mentions[id].role not in ROLE_FIELDS[field]: issue("ROLE_FIELD_MISMATCH",(id,),c)
    for c in claims:
        if not c.support_anchor_ids: issue("MISSING_SUPPORT",(c.id,),c)
        for id in c.support_anchor_ids:
            if id not in anchors: issue("UNKNOWN_ID",(id,),c)
        for id in c.depends_on:
            if id not in claim_map: issue("UNKNOWN_ID",(id,),c)
        for f in frame_ids(c):
            if f not in known_frames: issue("UNKNOWN_ID",(f,),c)
        if isinstance(c,FrameClaim):
            if c.anchor_id not in anchors: issue("UNKNOWN_ID",(c.anchor_id,),c)
            elif anchors[c.anchor_id].kind!="PREDICATE": issue("INVALID_FRAME_ANCHOR",(c.anchor_id,),c)
        if isinstance(c,(FieldOfClaim,SharedFieldClaim)):
            mention(c.mention_id,c,c.field)
            for f in frame_ids(c):
                if (f,c.version_id) not in known_versions: issue("UNKNOWN_VERSION",(f,c.version_id),c)
            if c.mention_id in prior_ids: issue("PRIOR_REFERENCE_REQUIRED",(c.mention_id,),c)
            if isinstance(c,SharedFieldClaim):
                if len(set(c.frame_ids))<2: issue("INVALID_SHARED_FIELD",(c.id,),c)
                if c.field in {"AMOUNT","QUANTITY"} and c.mode!="DISTRIBUTIVE": issue("SHARING_MODE_CONFLICT",(c.id,),c,severity="UNRESOLVED")
        if isinstance(c,(DiscourseClaim,ConditionClaim)) and (c.frame_id,c.version_id) not in known_versions: issue("UNKNOWN_VERSION",(c.frame_id,c.version_id),c)
        if isinstance(c,ConditionClaim) and c.anchor_id not in anchors: issue("UNKNOWN_ID",(c.anchor_id,),c)
        if isinstance(c,DiscourseClaim):
            if c.intent_status=="PROPOSED" and (c.context!="command" or c.disposition!="active"): issue("DISCOURSE_CONFLICT",(c.id,),c,severity="UNRESOLVED")
        if isinstance(c,(ReplacesClaim,RejectsClaim)):
            t=c.target
            if t.kind!="FRAME" and (t.frame_id,t.version_id) not in known_versions: issue("UNKNOWN_VERSION",(t.frame_id,t.version_id),c)
            if t.kind=="FIELD" and t.mention_id: mention(t.mention_id,c,t.field)
            if isinstance(c,ReplacesClaim):
                if t.kind=="FIELD" and t.field in c.carry_fields: issue("CORRECTION_SCOPE_CONFLICT",(c.id,),c)
                if t.kind=="FRAME" and len([v for f,v in initial_versions if f==t.frame_id and (f,v)!=(c.replacement_frame_id,c.replacement_version_id)])!=1: issue("AMBIGUOUS_FRAME_TARGET",(c.id,),c,severity="UNRESOLVED")
                if t.kind!="FRAME" and (t.frame_id,t.version_id)==(c.replacement_frame_id,c.replacement_version_id): issue("CYCLIC_RELATION",(c.id,),c)
        if isinstance(c,RefersToClaim):
            if c.reference_anchor_id not in anchors: issue("UNKNOWN_ID",(c.reference_anchor_id,),c)
            if c.requested_field=="OPERATION_TARGET":
                if c.carrier_mention_id is not None or c.antecedent_ids:issue("REFERENCE_TYPE_MISMATCH",(c.id,),c)
                for t in c.antecedent_version_targets:
                    if (t.frame_id,t.version_id) not in known_versions:issue("UNKNOWN_VERSION",(t.frame_id,t.version_id),c)
            else:
                if c.antecedent_version_targets:issue("REFERENCE_TYPE_MISMATCH",(c.id,),c)
                if c.carrier_mention_id:mention(c.carrier_mention_id,c,c.requested_field)
                for id in c.antecedent_ids:mention(id,c,c.requested_field)
        if isinstance(c,OperandOfClaim):
            mention(c.parent_mention_id,c);mention(c.operand_mention_id,c)
            if c.parent_mention_id in mentions and mentions[c.parent_mention_id].role not in {"transfer_amount","dependent_amount","asset_quantity","fraction","percentage"}: issue("ROLE_FIELD_MISMATCH",(c.parent_mention_id,),c)
            role={"FRACTION":"fraction","PERCENTAGE":"percentage"}.get(c.parameter)
            if role and c.operand_mention_id in mentions and mentions[c.operand_mention_id].role!=role: issue("ROLE_FIELD_MISMATCH",(c.operand_mention_id,),c)
        if isinstance(c,AlternativeClaim):
            ids=[b.id for b in c.branches]
            if not ids or len(set(ids))!=len(ids) or any(not b.frame_ids for b in c.branches): issue("UNDECLARED_ALTERNATIVE",(c.id,),c)
    graph={c.id:set(c.depends_on) for c in claims}
    for id in cyclic_nodes(graph): issue("CYCLIC_RELATION",(id,),claim_map[id])
    version_graph={}
    for c in claims:
        if not isinstance(c,ReplacesClaim):continue
        new=(c.replacement_frame_id,c.replacement_version_id)
        if c.target.kind=="FRAME":
            kk={k for k in initial_versions if k[0]==c.target.frame_id and k!=new}
            old=next(iter(kk)) if len(kk)==1 else None
        else:old=(c.target.frame_id,c.target.version_id)
        if old:
            version_graph.setdefault(new,set()).add(old)
            ancestors=set();todo=list(c.depends_on)
            while todo:
                id=todo.pop()
                if id in ancestors:continue
                ancestors.add(id)
                if id in claim_map:todo.extend(claim_map[id].depends_on)
            for creator in creators.get(old,[]):
                if creator.id not in ancestors:issue("MISSING_CORRECTION_DEPENDENCY",(c.id,creator.id),c)
    version_cycles=cyclic_nodes(version_graph)
    for c in claims:
        if isinstance(c,ReplacesClaim) and (c.replacement_frame_id,c.replacement_version_id) in version_cycles:issue("CYCLIC_RELATION",(c.id,),c)
    ops={c.parent_mention_id:set() for c in claims if isinstance(c,OperandOfClaim)}
    for c in claims:
        if isinstance(c,OperandOfClaim):ops[c.parent_mention_id].add(c.operand_mention_id)
    cycle=cyclic_nodes(ops)
    for c in claims:
        if isinstance(c,OperandOfClaim) and c.parent_mention_id in cycle: issue("CYCLIC_RELATION",tuple(cycle),c)
    scopes_by_id={x.mention_id:x for x in scopes}
    current={(c.frame_id,c.version_id) for c in claims if isinstance(c,DiscourseClaim) and c.intent_status=="PROPOSED"}
    for c in claims:
        if isinstance(c,(FieldOfClaim,SharedFieldClaim)):
            scope=scopes_by_id.get(c.mention_id)
            if scope and scope.producer_scope in {"NESTED_DATA","NESTED_OPERAND","EXCLUDED_BY_SCOPE"} and any((f,c.version_id) in current for f in frame_ids(c)):
                issue("SCOPE_USAGE_CONFLICT",(c.mention_id,),c,severity="UNRESOLVED")
    # Block dependent claims and complete malformed frame components; no repaired edge.
    while True:
        more={c.id for c in claims if set(c.depends_on)&blocked or set(frame_ids(c))&affected}
        if more<=blocked:break
        blocked |= more
    return IntegrityReport(issues=tuple(sorted(issues,key=content_sha256)),blocked_relation_ids=tuple(sorted(blocked)),affected_frame_ids=tuple(sorted(affected)),global_error=global_error)
