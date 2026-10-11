"""Materialize declared membership and sharing; do not propose interpretations."""
import json
from collections import defaultdict
from .base import FIELDS
from .relations import FrameClaim, FieldOfClaim, SharedFieldClaim, AlternativeClaim, CoordinatedClaim, RejectsClaim
from .ir import FieldBinding, OperationCandidate, CandidateGroup, CompilationIssue, BindingAssembly
from .serialization import content_sha256
from .integrity import frame_ids


def candidate_id(frame_id, version_id):
    return json.dumps([frame_id,version_id],ensure_ascii=False,separators=(",",":"))


def _exclusive_pair(f,g,bundle):
    for c in bundle.claims:
        if isinstance(c,AlternativeClaim):
            ff={b.id for b in c.branches if f in b.frame_ids};gg={b.id for b in c.branches if g in b.frame_ids}
            if ff and gg and not ff&gg:return True
    return False


def bindings_for(frame_id,version_id,bundle,integrity):
    table=defaultdict(list);issues=[]
    for c in bundle.claims:
        if isinstance(c,(FieldOfClaim,SharedFieldClaim)) and frame_id in frame_ids(c) and c.version_id==version_id:
            if c.id in integrity.blocked_relation_ids:
                # Preserve rejected relation evidence as unresolved, never a bound value.
                if frame_id not in integrity.affected_frame_ids:table[c.field].append((c,True))
            else:table[c.field].append((c,False))
    bindings=[]
    for name in FIELDS:
        entries=table[name]
        rejections=[r for r in bundle.claims if isinstance(r,RejectsClaim) and r.id not in integrity.blocked_relation_ids and r.target.kind=="FIELD" and r.target.frame_id==frame_id and r.target.version_id==version_id and r.target.field==name]
        rejected=[(c,blocked) for c,blocked in entries if any(r.target.mention_id is None or r.target.mention_id==c.mention_id for r in rejections)]
        entries=[e for e in entries if e not in rejected]
        mm=tuple(sorted({c.mention_id for c,_ in entries}));ids=tuple(sorted({c.id for c,_ in entries}))
        uncertain=any(blocked for _,blocked in entries) or len(mm)>1
        for c,_ in entries:
            if isinstance(c,FieldOfClaim):
                duplicates=[d for d in bundle.claims if isinstance(d,FieldOfClaim) and d.id not in integrity.blocked_relation_ids and d.mention_id==c.mention_id and d.field==c.field and d.frame_id!=c.frame_id and not _exclusive_pair(c.frame_id,d.frame_id,bundle)]
                if duplicates:
                    uncertain=True;issues.append(CompilationIssue(category="UNDECLARED_SHARING",affected_ids=(frame_id,c.mention_id),support_ids=tuple(sorted({c.id,*[d.id for d in duplicates]})),severity="UNRESOLVED"))
        modes={c.mode for c,_ in entries if isinstance(c,SharedFieldClaim)}
        if len(modes)>1:uncertain=True
        if len(mm)>1:issues.append(CompilationIssue(category="BINDING_CONFLICT",affected_ids=(frame_id,name),support_ids=ids,severity="UNRESOLVED"))
        bindings.append(FieldBinding(field=name,status="UNRESOLVED" if uncertain else "BOUND" if mm else "REJECTED" if rejected else "MISSING",mention_ids=mm or tuple(sorted({c.mention_id for c,_ in rejected})),support_ids=tuple(sorted({*ids,*[r.id for r in rejections]})),uncertainty_ids=ids if uncertain else (),shared_mode=next(iter(modes)) if len(modes)==1 else None))
    return tuple(bindings),tuple(issues)


def assemble_bindings(snapshot,bundle,integrity) -> BindingAssembly:
    if integrity.global_error:return BindingAssembly()
    candidates=[];groups=[];issues=[]
    for c in sorted(bundle.claims,key=lambda c:c.id):
        if isinstance(c,FrameClaim) and c.id not in integrity.blocked_relation_ids:
            bb,ii=bindings_for(c.frame_id,c.version_id,bundle,integrity);issues.extend(ii)
            candidates.append(OperationCandidate(id=candidate_id(c.frame_id,c.version_id),frame_id=c.frame_id,version_id=c.version_id,goal=c.goal,bindings=bb,support_ids=(c.id,),snapshot_sha256=content_sha256(snapshot),bundle_sha256=content_sha256(bundle)))
        if isinstance(c,AlternativeClaim) and c.id not in integrity.blocked_relation_ids:
            groups.append(CandidateGroup(id=c.group_id,kind="EXCLUSIVE",member_frame_ids=tuple(sorted({f for b in c.branches for f in b.frame_ids})),branches=tuple(sorted(c.branches,key=lambda b:b.id)),support_ids=(c.id,)))
        if isinstance(c,CoordinatedClaim) and c.id not in integrity.blocked_relation_ids:
            groups.append(CandidateGroup(id=c.group_id,kind="COORDINATED",member_frame_ids=tuple(sorted(set(c.frame_ids))),support_ids=(c.id,)))
    return BindingAssembly(candidates=tuple(sorted(candidates,key=lambda c:c.id)),groups=tuple(sorted(groups,key=lambda g:g.id)),issues=tuple(sorted(set(issues),key=content_sha256)))
