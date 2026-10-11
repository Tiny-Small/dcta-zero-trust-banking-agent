"""Apply explicit version/lifecycle relations; no correction/discourse discovery."""
from collections import defaultdict
from .base import FIELDS
from .bindings import bindings_for, candidate_id
from .ir import *
from .relations import ReplacesClaim, RejectsClaim, DiscourseClaim, ConditionClaim
from .serialization import content_sha256


def _rebuild(record, **changes):
    return type(record).model_validate({**record.model_dump(),**changes})


def assemble_discourse(snapshot,bundle,bindings,integrity) -> DiscourseAssembly:
    if integrity.global_error:return DiscourseAssembly()
    candidates={(c.frame_id,c.version_id):c for c in bindings.candidates};prior={}
    if snapshot.prior_context:
        for v in snapshot.prior_context.versions:prior[(v.frame_id,v.version_id)]=v
    issues=list(bindings.issues);revisions=[]
    claims=[c for c in bundle.claims if c.id not in integrity.blocked_relation_ids]
    replacements=[c for c in claims if isinstance(c,ReplacesClaim)]
    dependencies={c.id:set(c.depends_on) for c in claims};remaining={c.id:c for c in claims}
    ordered=[]
    while remaining:
        ready=sorted(id for id in remaining if not dependencies[id].intersection(remaining))
        if not ready:break # Integrity already reports cycles.
        batch=[remaining.pop(id) for id in ready]
        ordered.extend(c for c in batch if isinstance(c,ReplacesClaim))
    conflicts=defaultdict(list)
    base_keys=set(candidates)|set(prior)
    def target_key(r):
        t=r.target
        if t.kind=="FRAME":
            keys=[k for k in base_keys if k[0]==t.frame_id and k!=(r.replacement_frame_id,r.replacement_version_id)]
            return keys[0] if len(keys)==1 else None
        return (t.frame_id,t.version_id)
    for r in ordered:
        key=target_key(r);old=candidates.get(key) or prior.get(key)
        if old is None:
            issues.append(CompilationIssue(category="UNRESOLVED_CORRECTION_TARGET",affected_ids=(r.id,),support_ids=(r.id,),severity="UNRESOLVED"));continue
        new_key=(r.replacement_frame_id,r.replacement_version_id)
        bb,ii=bindings_for(*new_key,bundle,integrity);issues.extend(ii)
        oldfields={b.field:b for b in old.bindings} if isinstance(old,OperationCandidate) else {b.field:FieldBinding(field=b.field,status="BOUND",mention_ids=b.mention_ids) for b in old.fields}
        combined=[]
        for b in bb:
            if b.field in r.carry_fields:
                previous=oldfields.get(b.field)
                if b.mention_ids:
                    issues.append(CompilationIssue(category="CARRY_REPLACEMENT_CONFLICT",affected_ids=(r.id,b.field),support_ids=(r.id,*b.support_ids),severity="UNRESOLVED"))
                    b=_rebuild(b,status="UNRESOLVED")
                elif previous:
                    b=_rebuild(previous,support_ids=tuple(sorted({*previous.support_ids,r.id})))
            # A carried binding is materialized before explicit field rejection;
            # negative constraints apply equally to direct and carried membership.
            rr=[x for x in claims if isinstance(x,RejectsClaim) and x.target.kind=="FIELD" and x.target.frame_id==new_key[0] and x.target.version_id==new_key[1] and x.target.field==b.field and (x.target.mention_id is None or x.target.mention_id in b.mention_ids)]
            if rr and b.mention_ids:
                kept=tuple(m for m in b.mention_ids if not any(x.target.mention_id is None or x.target.mention_id==m for x in rr))
                b=_rebuild(b,status=b.status if kept else "REJECTED",mention_ids=kept or b.mention_ids,support_ids=tuple(sorted({*b.support_ids,*[x.id for x in rr]})))
            combined.append(b)
        existing=candidates.get(new_key)
        goal=existing.goal if existing else old.goal
        support=tuple(sorted({r.id,*(existing.support_ids if existing else ())}))
        new=OperationCandidate(id=candidate_id(*new_key),frame_id=new_key[0],version_id=new_key[1],goal=goal,bindings=tuple(combined),support_ids=support,snapshot_sha256=content_sha256(snapshot),bundle_sha256=content_sha256(bundle))
        if existing and any(x.kind=="REPLACES" and x.replacement_candidate_id==new.id for x in revisions):
            issues.append(CompilationIssue(category="CORRECTION_CONFLICT",affected_ids=(new.id,),support_ids=(r.id,),severity="UNRESOLVED"))
            # Do not overwrite a previously materialized branch.
            continue
        candidates[new_key]=new;conflicts[key].append(new_key)
        revisions.append(RevisionRelation(id=r.id,kind="REPLACES",target=r.target,replacement_candidate_id=new.id,carry_fields=r.carry_fields,support_ids=(r.id,)))
    conflict_keys=set()
    for target,news in conflicts.items():
        if len(news)>1:
            conflict_keys.add(target);conflict_keys.update(news)
            issues.append(CompilationIssue(category="CORRECTION_CONFLICT",affected_ids=tuple(sorted(candidate_id(*k) for k in {target,*news})),severity="UNRESOLVED"))
    # Uncertainty in a source version cannot be removed by merely carrying it.
    while True:
        descendants={(r.replacement_frame_id,r.replacement_version_id) for r in ordered if target_key(r) in conflict_keys}
        if descendants<=conflict_keys:break
        conflict_keys |= descendants
    projections={}
    for key,c in sorted({**prior,**candidates}.items()):
        dc=[r for r in claims if isinstance(r,DiscourseClaim) and (r.frame_id,r.version_id)==key]
        interpretations={(d.context,d.disposition,d.intent_status) for d in dc}
        conditions=tuple(sorted({r.anchor_id for r in claims if isinstance(r,ConditionClaim) and (r.frame_id,r.version_id)==key}))
        support=tuple(sorted({r.id for r in dc}|{r.id for r in claims if isinstance(r,ConditionClaim) and (r.frame_id,r.version_id)==key}))
        if len(interpretations)==1:
            ctx,disp,status=next(iter(interpretations));projections[key]=IntentProjection(candidate_id=c.id,context=ctx,disposition=disp,intent_status=status,support_ids=support,condition_anchor_ids=conditions)
        else:
            projections[key]=IntentProjection(candidate_id=c.id,support_ids=support,condition_anchor_ids=conditions)
            if dc:issues.append(CompilationIssue(category="DISCOURSE_CONFLICT",affected_ids=(c.id,),support_ids=support,severity="UNRESOLVED"))
    for r in ordered:
        key=target_key(r)
        if key in projections and any(x.id==r.id for x in revisions):
            projections[key]=_rebuild(projections[key],disposition="superseded",intent_status="NOT_CURRENT",support_ids=tuple(sorted({*projections[key].support_ids,r.id})))
    for r in claims:
        if not isinstance(r,RejectsClaim):continue
        revisions.append(RevisionRelation(id=r.id,kind="REJECTS",target=r.target,support_ids=(r.id,)))
        keys=[k for k in projections if k[0]==r.target.frame_id and (r.target.kind=="FRAME" or k[1]==r.target.version_id)]
        if r.target.kind!="FIELD":
            for key in keys:projections[key]=_rebuild(projections[key],disposition="rejected",intent_status="NOT_CURRENT",support_ids=tuple(sorted({*projections[key].support_ids,r.id})))
    for key in conflict_keys:
        if key in projections:projections[key]=_rebuild(projections[key],disposition="unresolved",intent_status="UNRESOLVED")
    return DiscourseAssembly(candidates=tuple(sorted(candidates.values(),key=lambda c:c.id)),groups=bindings.groups,issues=tuple(sorted(set(issues),key=content_sha256)),projections=tuple(sorted(projections.values(),key=lambda p:p.candidate_id)),revisions=tuple(sorted(revisions,key=lambda r:r.id)))
