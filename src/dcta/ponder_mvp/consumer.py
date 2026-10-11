"""Current-intent consumer and explicit allocation clarification. No lookup/execution."""
from typing import Literal
from dcta.ponder.base import FrozenRecord
from dcta.ponder.input import SemanticMention
from dcta.ponder.ir import PonderCompilation,OperationCandidate,IntentProjection,FieldBinding,CandidateGroup,UnresolvedReference,CompilationIssue
from dcta.ponder.compiler import compile_intent
from dcta.ponder.serialization import content_sha256
from dcta.ponder.relations import RelationDecisionBundle,RejectsClaim,FrameTarget

class CurrentCandidate(FrozenRecord):
    candidate: OperationCandidate
    projection: IntentProjection
    mentions: tuple[SemanticMention,...]
    unresolved_fields: tuple[FieldBinding,...]

class ConsumerView(FrozenRecord):
    schema_version: Literal['ponder-consumer-v1']='ponder-consumer-v1'
    status: Literal['OK','PARTIAL_INPUT','CONTRACT_ERROR']
    compilation_sha256: str
    compilation: PonderCompilation
    current: tuple[CurrentCandidate,...]=()
    unresolved_groups: tuple[CandidateGroup,...]=()
    unresolved_references: tuple[UnresolvedReference,...]=()
    unresolved_projections: tuple[IntentProjection,...]=()
    issues: tuple[CompilationIssue,...]=()


def consume(compilation: PonderCompilation) -> ConsumerView:
    c=PonderCompilation.model_validate(compilation)
    if c.input_snapshot is None or c.relation_bundle is None:raise ValueError('consumer integrity: missing immutable inputs')
    # Replay verifies projections, bindings, candidate versions and all hashes;
    # neither OK nor caller-edited candidate IDs confer current intent.
    replay=compile_intent(c.input_snapshot,c.relation_bundle)
    if content_sha256(replay)!=content_sha256(c):raise ValueError('consumer integrity: compilation differs from deterministic replay')
    current=[];groups=()
    if c.status=='OK':
        projections={p.candidate_id:p for p in c.projections}
        mentions={m.id:m for m in c.input_snapshot.semantic_mentions}
        if c.input_snapshot.prior_context:mentions.update({m.id:m for m in c.input_snapshot.prior_context.semantic_mentions})
        for candidate in c.candidates:
            if candidate.id not in c.current_candidate_ids:continue
            p=projections[candidate.id]
            if (p.context,p.disposition,p.intent_status)!=('command','active','PROPOSED'):raise ValueError('consumer integrity: undeclared current candidate')
            mids={m for b in candidate.bindings for m in b.mention_ids}
            current.append(CurrentCandidate(candidate=candidate,projection=p,mentions=tuple(mentions[m] for m in sorted(mids)),unresolved_fields=tuple(b for b in candidate.bindings if b.status!='BOUND')))
        groups=tuple(g for g in c.groups if g.id in c.requested_group_ids)
    return ConsumerView(status=c.status,compilation_sha256=content_sha256(c),compilation=c,current=tuple(current),unresolved_groups=groups,
        unresolved_references=c.references,unresolved_projections=tuple(p for p in c.projections if p.intent_status=='UNRESOLVED'),issues=c.issues)

class AllocationResolution(FrozenRecord):
    parent_compilation_sha256: str
    group_id: str
    branch_id: str
    parent_compilation: PonderCompilation
    compilation: PonderCompilation


def clarify_allocation(compilation,group_id,branch_id,*,expected_compilation_sha256):
    view=consume(compilation)
    if view.status!='OK' or view.compilation_sha256!=expected_compilation_sha256:raise ValueError('stale/blocked allocation clarification')
    group=next((g for g in view.unresolved_groups if g.id==group_id),None)
    branch=next((b for b in group.branches if b.id==branch_id),None) if group else None
    if branch is None:raise ValueError('allocation branch not offered')
    c=view.compilation;old=c.relation_bundle
    alternative=next(r for r in old.claims if r.kind=='ALTERNATIVE' and r.group_id==group_id)
    unchosen=set(group.member_frame_ids)-set(branch.frame_ids)
    # The user's branch choice withdraws those alternative FIELD memberships
    # from the new semantic decision bundle, not from the historical snapshot.
    # Otherwise formerly exclusive occurrences become undeclared sharing.
    claims=[]
    for r in old.claims:
        if r.id==alternative.id:continue
        if r.kind=='FIELD_OF' and r.frame_id in unchosen:continue
        if r.kind=='SHARED_FIELD' and set(r.frame_ids)<=unchosen:continue
        if r.kind=='SHARED_FIELD' and set(r.frame_ids)&unchosen:raise ValueError('unsupported cross-branch shared relation')
        claims.append(r)
    frames={r.frame_id:r for r in old.claims if r.kind=='FRAME'}
    for frame in group.member_frame_ids:
        if frame in branch.frame_ids:continue
        claims.append(RejectsClaim(id='clarify:'+group_id+':'+branch_id+':'+frame,support_anchor_ids=alternative.support_anchor_ids,
            depends_on=(frames[frame].id,),target=FrameTarget(frame_id=frame)))
    bundle=RelationDecisionBundle(snapshot_sha256=old.snapshot_sha256,policy_identity=old.policy_identity+'+explicit-user-allocation',
        policy_version=old.policy_version+':'+branch_id,claims=tuple(sorted(claims,key=lambda r:r.id)))
    successor=compile_intent(c.input_snapshot,bundle)
    return AllocationResolution(parent_compilation_sha256=view.compilation_sha256,group_id=group_id,branch_id=branch_id,parent_compilation=c,compilation=successor)
