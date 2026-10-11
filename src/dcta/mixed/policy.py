"""One investment + one monetary predicate; registered whole graph, no cross-product."""
from dcta.ponder.base import ROLE_FIELDS
from dcta.ponder.compiler import compile_intent
from dcta.ponder.serialization import content_sha256
from dcta.ponder.relations import CoordinatedClaim,RelationDecisionBundle
from dcta.ponder_mvp.registry import FrameSpec,Packet,Registry,Limits
from dcta.ponder_mvp.packets import _field,claim,frame_dep
from dcta.ponder_mvp.selection import emit_bundle,MODES,parse_selection,_brief
from .records import ActionClaim,MixedRelationDecisionBundle,MixedInterpretation,InvestmentAction

VERSION='mixed-relation-policy-v1'
INV={'buy':'BUY','sell':'SELL','invest':'UNSPECIFIED'}
BANK={'send','transfer','move','pay','give'}
RELATION_POLICY=('Select the complete registered heterogeneous graph, using raw source, supplied semantic mentions and scope. '
 'Exactly one investment and one transfer/payment hypothesis are supported; no missing/extra operations or cross-bindings. '
 'Role compatibility restricts candidates but does not prove the requested binding. Select UNSUPPORTED if the meaning is not offered. '
 'QUANTITY is shares, never money; AMOUNT/CURRENCY is monetary, never investment consideration. '
 'Do not share source/account/person across goals. Do not infer BUY from investment. Action must be explicitly supported by its supplied predicate evidence. '
 'History, hypothetical, negation and quoted data are not current intent. NONE means no supported operation; never simplify complexity.')


def build_registry(snapshot):
    digest=content_sha256(snapshot);pred=[a for a in snapshot.relational_anchors if a.kind=='PREDICATE']
    ms=[m for m in snapshot.semantic_mentions if m.origin=='CANONICAL'];counts=(('mentions',len(ms)),('predicates',len(pred)))
    def stop(reason,status='UNSUPPORTED'):return Registry(snapshot_sha256=digest,status=status,reason=reason,counts=counts+(('packets',0),))
    if len(ms)>Limits().max_mentions:return stop('mention limit','LIMIT_EXCEEDED')
    if snapshot.prior_context:return stop('prior-context mixed topology unsupported')
    if len(pred)!=2:return stop('requires exactly two explicit predicates; no partial simplification')
    inv=[a for a in pred if a.evidence.text.casefold() in INV];bank=[a for a in pred if a.evidence.text.casefold() in BANK]
    if len(inv)!=1 or len(bank)!=1:return stop('requires one investment and one transfer/payment predicate')
    if any(a.kind in {'CORRECTION','NEGATION','CONDITION','REFERENCE','DISCOURSE'} for a in snapshot.relational_anchors):return stop('complex discourse/correction/reference topology unsupported')
    coord=[a for a in snapshot.relational_anchors if a.kind=='COORDINATION']
    if not coord or any(a.evidence.text.casefold()!='and' for a in coord):return stop('only explicit simple and-coordination supported')
    nested={p.mention_id for p in snapshot.ping_projection if p.producer_scope in {'NESTED_DATA','EXCLUDED_BY_SCOPE'}}
    usable=[m for m in ms if m.id not in nested]
    if any(m.role in {'fraction','percentage','dependent_amount'} for m in usable):return stop('symbolic mixed topology unsupported')
    frames=tuple(FrameSpec(frame_id='mixed:'+a.id,anchor_id=a.id) for a in sorted(pred,key=lambda a:a.evidence.start))
    frame_by_anchor={f.anchor_id:f for f in frames};claims=[]
    for field,roles in ROLE_FIELDS.items():
        pool=[m for m in usable if m.role in roles]
        if len(pool)>1:return stop('multiple compatible '+field+' occurrences require unoffered semantic alternatives')
        if pool:
            target=frame_by_anchor[(inv if field in {'ASSET','QUANTITY'} else bank)[0].id]
            claims.append(_field(field,pool[0],target))
    if any(m.role=='beneficiary' for m in usable) and any(m.role=='destination_account' for m in usable):return stop('two distinct monetary targets unsupported')
    claims.append(claim(CoordinatedClaim,tuple(a.id for a in pred+coord),depends_on=tuple(frame_dep(f) for f in frames),group_id='mixed:bundle',frame_ids=tuple(f.frame_id for f in frames)))
    packet=Packet(id='mixed:p0',kind='HETEROGENEOUS',frames=frames,claims=tuple(claims))
    return Registry(snapshot_sha256=digest,status='READY',packets=(packet,),counts=counts+(('frames',2),('packets',1),('primitive_relations',len(claims))))


def build_request(snapshot,registry):
    if registry.status!='READY' or registry.snapshot_sha256!=content_sha256(snapshot):raise ValueError(registry.status+': '+registry.reason)
    q={'binding':{'type':'choice','instructions':RELATION_POLICY,'criteria':{p.id:_brief(p,snapshot) for p in registry.packets}}}
    q['binding']['criteria'].update(NONE='No operations supported.',UNSUPPORTED='Complete interpretation not offered.')
    for a in snapshot.relational_anchors:
        if a.kind!='PREDICATE':continue
        word=a.evidence.text.casefold();goals=('investment',) if word in INV else ('transfer','payment')
        q['anchor:'+a.id]={'type':'choice','instructions':RELATION_POLICY,'criteria':{g+'_'+mode:'Registered goal/discourse interpretation.' for g in goals for mode in MODES}}
        q['anchor:'+a.id]['criteria'].update(NONE='No hypothesis.',UNSUPPORTED='Not represented.')
        if word in INV:
            q['action:'+a.id]={'type':'choice','instructions':RELATION_POLICY,'criteria':{INV[word]:'Source-supported investment action.','UNSPECIFIED':'Action not established; never default BUY.'}}
    state={'mixed_stage':'relation','policy_version':VERSION,'transcript':snapshot.current_source.text,'snapshot':snapshot.model_dump(mode='json'),'anchors':[a.model_dump(mode='json') for a in snapshot.relational_anchors], 'registry':registry.model_dump(mode='json')}
    return state,q


def materialize(compilation,relations):
    anchors={a.id:a for a in compilation.input_snapshot.relational_anchors};frames={r.frame_id:r for r in relations.core.claims if r.kind=='FRAME'}
    if len({a.frame_id for a in relations.action_claims})!=len(relations.action_claims):raise ValueError('duplicate action frame')
    expected={f.frame_id for f in frames.values() if f.goal=='investment'}
    if {a.frame_id for a in relations.action_claims}!=expected:raise ValueError('investment action membership')
    result=[]
    for a in relations.action_claims:
        anchor=anchors.get(a.anchor_id);f=frames.get(a.frame_id)
        if anchor is None or anchor.kind!='PREDICATE' or f is None or f.anchor_id!=a.anchor_id or a.evidence!=anchor.evidence:raise ValueError('action source/frame membership')
        allowed={INV.get(anchor.evidence.text.casefold()),'UNSPECIFIED'}
        if a.action not in allowed:raise ValueError('unsupported action predicate')
        for c in compilation.candidates:
            if c.frame_id==a.frame_id:
                result.append(InvestmentAction(candidate_id=c.id,frame_id=c.frame_id,version_id=c.version_id,candidate_sha256=content_sha256(c),snapshot_sha256=c.snapshot_sha256,relation_bundle_sha256=content_sha256(relations),action=a.action,anchor_id=a.anchor_id,evidence=a.evidence))
    return tuple(result)


def verify_interpretation(value):
    i=MixedInterpretation.model_validate(value);c=i.compilation
    if c.input_snapshot is None or c.relation_bundle!=i.relations.core:raise ValueError('mixed relation provenance')
    if compile_intent(c.input_snapshot,i.relations.core)!=c or materialize(c,i.relations)!=i.actions:raise ValueError('mixed deterministic replay')
    return i


def assemble_snapshot(snapshot,provider):
    registry=build_registry(snapshot)
    if registry.status!='READY':raise ValueError(registry.status+': '+registry.reason)
    state,q=build_request(snapshot,registry);response=provider.decide(state=state,questions=q);choices=parse_selection(response,q,model=provider.model)
    if any(v=='UNSUPPORTED' for v in choices.values()):raise ValueError('UNSUPPORTED: interpretation not offered')
    core=emit_bundle(snapshot,registry,choices)
    core=RelationDecisionBundle.model_validate({**core.model_dump(),'policy_version':VERSION})
    anchors={a.id:a for a in snapshot.relational_anchors};actions=[]
    for f in core.claims:
        if f.kind=='FRAME' and f.goal=='investment':
            a=anchors[f.anchor_id];actions.append(ActionClaim(frame_id=f.frame_id,anchor_id=f.anchor_id,action=choices['action:'+a.id],evidence=a.evidence))
    relations=MixedRelationDecisionBundle(core=core,action_claims=tuple(actions));c=compile_intent(snapshot,core)
    return verify_interpretation(MixedInterpretation(compilation=c,relations=relations,actions=materialize(c,relations)))
