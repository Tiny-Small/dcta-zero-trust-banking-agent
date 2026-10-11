"""Immutable transport from already-versioned results. No compiler/policy/search calls."""
import hashlib
from typing import Literal
from dcta.ponder.base import FrozenRecord
from dcta.ponder.input import PonderInputSnapshot,EvidenceRef
from dcta.ponder.ir import CandidateGroup,UnresolvedReference,IntentProjection,CompilationIssue,OperationCandidate,ValueExpression
from dcta.ponder.serialization import content_sha256
from dcta.ponder_mvp.consumer import ConsumerView,CurrentCandidate,AllocationResolution
from dcta.ponder_mvp.grounding import GroundingState,GroundedField,Directory

class EvidenceItem(FrozenRecord):
    id: str
    evidence: EvidenceRef

class BranchSelection(FrozenRecord):
    group: CandidateGroup
    branch_id: str
    parent_compilation_sha256: str
    successor_compilation_sha256: str
    parent_snapshot_sha256: str
    parent_requested_group_ids: tuple[str,...]
    parent_current: tuple[CurrentCandidate,...]

class ValidationInput(FrozenRecord):
    schema_version: Literal['semantic-validation-input-v1']='semantic-validation-input-v1'
    producer_status: Literal['OK','PARTIAL_INPUT','CONTRACT_ERROR']
    snapshot: PonderInputSnapshot
    snapshot_sha256: str
    bundle_sha256: str
    compilation_sha256: str
    consumer_sha256: str
    context: tuple[CurrentCandidate,...]
    context_sha256: tuple[str,...]
    targets: tuple[CurrentCandidate,...]
    focus_candidate_id: str | None=None
    evidence: tuple[EvidenceItem,...]
    expressions: tuple[ValueExpression,...]
    groups: tuple[CandidateGroup,...]
    requested_group_ids: tuple[str,...]
    unresolved_references: tuple[UnresolvedReference,...]
    unresolved_projections: tuple[IntentProjection,...]
    issues: tuple[CompilationIssue,...]
    grounding: GroundingState | None
    grounding_sha256: str | None
    grounding_revision: int | None
    directory_sha256: str | None
    directory_version: str | None=None
    directory: Directory | None=None
    grounding_parents: tuple[GroundingState,...]=()
    branch_selection: BranchSelection | None=None
    transport_errors: tuple[str,...]=()


def build_input(view,grounding,*,grounding_parents=(),directory=None,focus_candidate_id=None,allocation_resolution=None):
    view=ConsumerView.model_validate(view);c=view.compilation
    if c.input_snapshot is None:raise ValueError('versioned input source is required')
    snapshot=c.input_snapshot;errors=[]
    if view.compilation_sha256!=content_sha256(c):errors.append('consumer compilation hash')
    if view.status!=c.status:errors.append('consumer status')
    if content_sha256(snapshot)!=c.snapshot_sha256:errors.append('compilation snapshot hash')
    if c.relation_bundle is None or content_sha256(c.relation_bundle)!=c.bundle_sha256:errors.append('compilation bundle hash')
    if view.unresolved_projections!=tuple(p for p in c.projections if p.intent_status=='UNRESOLVED'):errors.append('consumer unresolved projections')
    cmap={x.id:x for x in c.candidates};pmap={p.candidate_id:p for p in c.projections}
    expected=set(c.current_candidate_ids) if c.status=='OK' else set()
    if {x.candidate.id for x in view.current}!=expected:errors.append('declared current membership')
    for item in view.current:
        if cmap.get(item.candidate.id)!=item.candidate or pmap.get(item.candidate.id)!=item.projection:errors.append('changed current candidate/projection content')
    if view.unresolved_groups!=tuple(g for g in c.groups if g.id in c.requested_group_ids) and c.status=='OK':errors.append('consumer groups')
    if view.unresolved_references!=c.references or view.issues!=c.issues:errors.append('consumer unresolved diagnostics')
    grounding=GroundingState.model_validate(grounding) if grounding is not None else None
    evidence=[EvidenceItem(id='source:full',evidence=EvidenceRef(source_id=snapshot.current_source.id,start=0,end=len(snapshot.current_source.text),text=snapshot.current_source.text))]
    mentions=list(snapshot.semantic_mentions);anchors=list(snapshot.relational_anchors)
    if snapshot.prior_context:
        mentions.extend(snapshot.prior_context.semantic_mentions);anchors.extend(snapshot.prior_context.relational_anchors)
        for source in snapshot.prior_context.sources:evidence.append(EvidenceItem(id='source:'+source.id,evidence=EvidenceRef(source_id=source.id,start=0,end=len(source.text),text=source.text)))
    evidence.extend(EvidenceItem(id='mention:'+m.id,evidence=m.evidence) for m in mentions)
    evidence.extend(EvidenceItem(id='anchor:'+a.id,evidence=a.evidence) for a in anchors)
    branch=None
    if allocation_resolution is not None:
        ar=AllocationResolution.model_validate(allocation_resolution)
        group=next((g for g in ar.parent_compilation.groups if g.id==ar.group_id),None)
        if group is None or not any(b.id==ar.branch_id for b in group.branches):errors.append('unoffered allocation branch')
        elif content_sha256(ar.compilation)!=view.compilation_sha256 or content_sha256(ar.parent_compilation)!=ar.parent_compilation_sha256:errors.append('stale allocation clarification')
        else:
            parent=ar.parent_compilation
            mm={m.id:m for m in parent.input_snapshot.semantic_mentions} if parent.input_snapshot else {}
            if parent.input_snapshot and parent.input_snapshot.prior_context:mm.update({m.id:m for m in parent.input_snapshot.prior_context.semantic_mentions})
            pp={p.candidate_id:p for p in parent.projections};parent_current=[]
            for candidate in parent.candidates:
                projection=pp.get(candidate.id)
                if projection is None or (projection.context,projection.disposition,projection.intent_status)!=('command','active','PROPOSED'):continue
                mids={m for b in candidate.bindings for m in b.mention_ids}
                if any(mid not in mm for mid in mids) or candidate.id not in pp:errors.append('allocation parent evidence membership');continue
                parent_current.append(CurrentCandidate(candidate=candidate,projection=pp[candidate.id],mentions=tuple(mm[mid] for mid in sorted(mids)),unresolved_fields=tuple(b for b in candidate.bindings if b.status!='BOUND')))
            branch=BranchSelection(group=group,branch_id=ar.branch_id,parent_compilation_sha256=ar.parent_compilation_sha256,successor_compilation_sha256=view.compilation_sha256,
                parent_snapshot_sha256=parent.snapshot_sha256,parent_requested_group_ids=parent.requested_group_ids,parent_current=tuple(parent_current))
    if directory is not None:
        directory=Directory.model_validate(directory)
        if grounding and content_sha256(directory)!=grounding.directory_sha256:errors.append('directory hash')
    targets=tuple(x for x in view.current if focus_candidate_id is None or x.candidate.id==focus_candidate_id)
    return ValidationInput(producer_status=view.status,snapshot=snapshot,snapshot_sha256=c.snapshot_sha256,bundle_sha256=c.bundle_sha256,
        compilation_sha256=view.compilation_sha256,consumer_sha256=content_sha256(view),context=view.current,context_sha256=tuple(content_sha256(x) for x in view.current),
        targets=targets,focus_candidate_id=focus_candidate_id,evidence=tuple(evidence),expressions=c.expressions,groups=c.groups,requested_group_ids=c.requested_group_ids,
        unresolved_references=view.unresolved_references,unresolved_projections=view.unresolved_projections,issues=view.issues,
        grounding=grounding,grounding_sha256=content_sha256(grounding) if grounding else None,grounding_revision=grounding.revision if grounding else None,
        directory_sha256=grounding.directory_sha256 if grounding else None,directory_version=directory.version if directory else None,directory=directory,
        grounding_parents=tuple(grounding_parents),branch_selection=branch,transport_errors=tuple(errors))


def integrity_errors(data):
    data=ValidationInput.model_validate(data);errors=list(data.transport_errors)
    sources={data.snapshot.current_source.id:data.snapshot.current_source}
    mentions={m.id:m for m in data.snapshot.semantic_mentions}
    if data.snapshot.prior_context:
        sources.update({s.id:s for s in data.snapshot.prior_context.sources});mentions.update({m.id:m for m in data.snapshot.prior_context.semantic_mentions})
    if content_sha256(data.snapshot)!=data.snapshot_sha256:errors.append('snapshot content hash')
    for source in sources.values():
        if hashlib.sha256(source.text.encode()).hexdigest()!=source.text_sha256:errors.append('source text hash')
    expected_evidence={'source:full':EvidenceRef(source_id=data.snapshot.current_source.id,start=0,end=len(data.snapshot.current_source.text),text=data.snapshot.current_source.text)}
    anchors={a.id:a for a in data.snapshot.relational_anchors}
    if data.snapshot.prior_context:
        anchors.update({a.id:a for a in data.snapshot.prior_context.relational_anchors})
        expected_evidence.update({'source:'+s.id:EvidenceRef(source_id=s.id,start=0,end=len(s.text),text=s.text) for s in data.snapshot.prior_context.sources})
    expected_evidence.update({'mention:'+m.id:m.evidence for m in mentions.values()})
    expected_evidence.update({'anchor:'+a.id:a.evidence for a in anchors.values()})
    if {e.id:e.evidence for e in data.evidence}!=expected_evidence:errors.append('source evidence table membership/content')
    if len({e.id for e in data.evidence})!=len(data.evidence):errors.append('duplicate evidence ID')
    for e in data.evidence:
        s=sources.get(e.evidence.source_id);v=e.evidence
        if s is None or not 0<=v.start<=v.end<=len(s.text) or s.text[v.start:v.end]!=v.text:errors.append('invalid source evidence span')
    if tuple(content_sha256(x) for x in data.context)!=data.context_sha256:errors.append('current context content hash')
    expected=tuple(x for x in data.context if data.focus_candidate_id is None or x.candidate.id==data.focus_candidate_id)
    if data.targets!=expected or (data.focus_candidate_id is not None and len(data.targets)!=1):errors.append('validation target membership')
    if len({x.candidate.id for x in data.context})!=len(data.context):errors.append('duplicate current candidate')
    for item in data.context:
        c=item.candidate;p=item.projection
        if c.snapshot_sha256!=data.snapshot_sha256 or c.bundle_sha256!=data.bundle_sha256:errors.append('candidate provenance hash')
        if p.candidate_id!=c.id or (p.context,p.disposition,p.intent_status)!=('command','active','PROPOSED'):errors.append('undeclared current projection')
        if len({b.field for b in c.bindings})!=len(c.bindings) or {b.field for b in c.bindings}!={'AMOUNT','CURRENCY','BENEFICIARY','SOURCE_ACCOUNT','DESTINATION_ACCOUNT','ASSET','QUANTITY','REFERENCE'}:errors.append('binding field registry')
        if any(aid not in anchors or anchors[aid].kind!='CONDITION' for aid in p.condition_anchor_ids):errors.append('condition anchor membership')
        mids={m for b in c.bindings for m in b.mention_ids}
        if {m.id for m in item.mentions}!=mids or any(mentions.get(m.id)!=m for m in item.mentions):errors.append('candidate evidence membership')
        if item.unresolved_fields!=tuple(b for b in c.bindings if b.status!='BOUND'):errors.append('missing unresolved binding transport')
    if len({e.id for e in data.expressions})!=len(data.expressions):errors.append('duplicate expression ID')
    for e in data.expressions:
        if e.mention_id is not None and e.mention_id not in mentions:errors.append('expression carrier membership')
        if any(mid not in mentions for mid in e.operand_ids):errors.append('expression operand membership')
        if any(aid not in anchors for aid in e.basis_anchor_ids):errors.append('expression basis membership')
    selection=data.branch_selection
    if selection:
        group=selection.group;branch=next((b for b in group.branches if b.id==selection.branch_id),None)
        parent_frames={x.candidate.frame_id for x in selection.parent_current}
        if group.kind!='EXCLUSIVE' or group.id not in selection.parent_requested_group_ids or not branch or not set(group.member_frame_ids)<=parent_frames or not all(set(b.frame_ids)<=set(group.member_frame_ids) and b.frame_ids for b in group.branches):errors.append('allocation choice not offered by parent')
        elif selection.successor_compilation_sha256!=data.compilation_sha256 or selection.parent_snapshot_sha256!=data.snapshot_sha256 or group.id in data.requested_group_ids:errors.append('allocation successor/source provenance')
        else:
            unchosen=set(group.member_frame_ids)-set(branch.frame_ids)
            expected={x.candidate.id:x for x in selection.parent_current if x.candidate.frame_id not in unchosen}
            actual={x.candidate.id:x for x in data.context}
            if set(expected)!=set(actual):errors.append('allocation selected/unrelated current membership')
            for cid in set(expected)&set(actual):
                old=expected[cid];new=actual[cid]
                if (old.candidate.frame_id,old.candidate.version_id,old.candidate.goal,old.candidate.bindings,old.mentions,old.projection)!=(new.candidate.frame_id,new.candidate.version_id,new.candidate.goal,new.candidate.bindings,new.mentions,new.projection):errors.append('allocation changes chosen/unrelated semantics')
    directory=data.directory
    if directory is not None:
        if content_sha256(directory)!=data.directory_sha256 or directory.version!=data.directory_version:errors.append('directory version/content hash')
        if len({e.id for e in directory.entities})!=len(directory.entities):errors.append('duplicate directory entity ID')
    g=data.grounding
    if g is None:
        if data.context:errors.append('missing grounding state')
        return tuple(sorted(set(errors)))
    if content_sha256(g)!=data.grounding_sha256 or g.revision!=data.grounding_revision:errors.append('grounding revision/content hash')
    if g.compilation_sha256!=data.compilation_sha256 or g.consumer_sha256!=data.consumer_sha256 or g.directory_sha256!=data.directory_sha256:errors.append('grounding parent provenance')
    cmap={x.candidate.id:x.candidate for x in data.context}
    if len({f.id for f in g.fields})!=len(g.fields):errors.append('duplicate grounding field')
    for f in g.fields:
        c=cmap.get(f.candidate_id);m=mentions.get(f.mention_id)
        if c is None or m is None:errors.append('grounding candidate/mention membership');continue
        kind={'BENEFICIARY':'PERSON','SOURCE_ACCOUNT':'ACCOUNT','DESTINATION_ACCOUNT':'ACCOUNT','ASSET':'ASSET'}.get(f.field)
        if len({e.id for e in f.matches})!=len(f.matches) or any(e.kind!=kind for e in f.matches):errors.append('grounding entity registry/kind')
        if directory is not None:
            registry={e.id:e for e in directory.entities}
            if any(registry.get(e.id)!=e for e in f.matches):errors.append('grounding entity directory membership/content')
        if (f.frame_id,f.version_id,f.candidate_sha256,f.snapshot_sha256,f.bundle_sha256)!=(c.frame_id,c.version_id,content_sha256(c),c.snapshot_sha256,c.bundle_sha256):errors.append('grounding candidate version/hash')
        if not any(b.field==f.field and f.mention_id in b.mention_ids for b in c.bindings) or f.evidence!=m.evidence or f.literal!=m.evidence.text:errors.append('grounding literal/binding integrity')
    parents=data.grounding_parents
    if g.revision<0 or len(parents)!=g.revision:errors.append('clarification parent chain')
    chain=(*parents,g)
    for i,node in enumerate(chain):
        if node.revision!=i or (node.compilation_sha256,node.consumer_sha256,node.directory_sha256)!=(g.compilation_sha256,g.consumer_sha256,g.directory_sha256):errors.append('clarification version chain')
        if i==0:
            if node.parent_sha256 is not None or node.decisions:errors.append('clarification initial state')
            if any(f.status=='RESOLVED' and len(f.matches)!=1 for f in node.fields):errors.append('unrecorded entity clarification')
            continue
        prev=chain[i-1];ph=content_sha256(prev)
        if node.parent_sha256!=ph or len(node.decisions)!=len(prev.decisions)+1 or node.decisions[:-1]!=prev.decisions:errors.append('clarification decision chain');continue
        d=node.decisions[-1];choice=next((ch for ch in prev.clarifications if ch.id==d.choice_id),None)
        if d.previous_state_sha256!=ph or choice is None or choice.field_id!=d.field_id or d.entity_id not in {e.id for e in choice.options}:errors.append('clarification stale/unoffered choice');continue
        before={f.id:f for f in prev.fields};after={f.id:f for f in node.fields}
        if set(before)!=set(after):errors.append('clarification field membership');continue
        for fid,field in before.items():
            expected=GroundedField.model_validate({**field.model_dump(),'status':'RESOLVED','selected_entity_id':d.entity_id}) if fid==d.field_id else field
            if after[fid]!=expected:errors.append('clarification field content change')
        if node.clarifications!=tuple(ch for ch in prev.clarifications if ch.id!=d.choice_id):errors.append('clarification remaining choices')
    return tuple(sorted(set(errors)))
