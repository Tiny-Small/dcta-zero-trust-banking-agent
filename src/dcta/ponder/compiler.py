"""Pure deterministic materialization of supplied semantics. No policy discovery."""
from .input import PonderInputSnapshot
from .relations import RelationDecisionBundle
from .ir import PonderCompilation, FieldBinding, OperationCandidate
from .integrity import check_integrity
from .bindings import assemble_bindings
from .discourse import assemble_discourse
from .expressions import assemble_expressions
from .serialization import content_sha256


def compile_intent(snapshot: PonderInputSnapshot, relation_bundle: RelationDecisionBundle) -> PonderCompilation:
    snapshot=PonderInputSnapshot.model_validate(snapshot)
    bundle=RelationDecisionBundle.model_validate(relation_bundle)
    snapshot_hash=content_sha256(snapshot);bundle_hash=content_sha256(bundle)
    integrity=check_integrity(snapshot,bundle)
    bindings=assemble_bindings(snapshot,bundle,integrity)
    discourse=assemble_discourse(snapshot,bundle,bindings,integrity)
    expressions=assemble_expressions(snapshot,bundle,discourse,integrity)
    issues=tuple(sorted(set(integrity.issues+discourse.issues+expressions.issues),key=content_sha256))
    unresolved={r.carrier_mention_id for r in expressions.references if r.carrier_mention_id}
    candidates=[]
    for c in discourse.candidates:
        bb=tuple(FieldBinding.model_validate({**b.model_dump(),"status":"UNRESOLVED","uncertainty_ids":tuple(sorted({*b.uncertainty_ids,*[r.id for r in expressions.references if r.carrier_mention_id in b.mention_ids]}))}) if b.status=="BOUND" and set(b.mention_ids)&unresolved else b for b in c.bindings)
        candidates.append(OperationCandidate.model_validate({**c.model_dump(),"bindings":bb}))
    exclusive={f for g in discourse.groups if g.kind=="EXCLUSIVE" for f in g.member_frame_ids}
    current={p.candidate_id for p in discourse.projections if p.intent_status=="PROPOSED" and p.disposition=="active" and p.context=="command"}
    current_ids=tuple(sorted(c.id for c in candidates if c.id in current and c.frame_id not in exclusive))
    requested=tuple(sorted(g.id for g in discourse.groups if g.kind=="EXCLUSIVE" and any(c.id in current and c.frame_id in g.member_frame_ids for c in candidates)))
    status="CONTRACT_ERROR" if integrity.global_error or any(i.severity=="ERROR" for i in issues) else "PARTIAL_INPUT" if snapshot.input_status=="PARTIAL_INPUT" or snapshot.current_source.finality=="PARTIAL" else "OK"
    return PonderCompilation(snapshot_sha256=snapshot_hash,bundle_sha256=bundle_hash,status=status,input_snapshot=snapshot,relation_bundle=bundle,candidates=tuple(candidates),groups=discourse.groups,issues=issues,projections=discourse.projections,revisions=discourse.revisions,expressions=expressions.expressions,references=expressions.references,current_candidate_ids=current_ids,requested_group_ids=requested)
