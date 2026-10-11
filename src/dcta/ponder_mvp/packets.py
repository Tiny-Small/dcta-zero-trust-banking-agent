"""Enumerate complete candidate interpretations. Never choose their semantics."""
import hashlib,json
from itertools import product,permutations,combinations
from dcta.ponder.base import ROLE_FIELDS
from dcta.ponder.serialization import content_sha256
from dcta.ponder.relations import (FieldOfClaim,SharedFieldClaim,CoordinatedClaim,
    ReplacesClaim,RejectsClaim,FieldTarget,AlternativeClaim,AlternativeBranch,
    OperandOfClaim,RefersToClaim)
from .registry import Limits,FrameSpec,Packet,Registry


def claim(cls,support,*,depends_on=(),**data):
    key=json.dumps([cls.__name__,support,depends_on,data],sort_keys=True,default=str)
    return cls(id='r:'+hashlib.sha256(key.encode()).hexdigest()[:18],support_anchor_ids=tuple(support),depends_on=tuple(depends_on),**data)


def frame_dep(frame):return 'frame:'+frame.frame_id


def _field(field,mention,frame,*,version='v0',dep=None):
    return claim(FieldOfClaim,(frame.anchor_id,),depends_on=(dep or frame_dep(frame),),
        frame_id=frame.frame_id,version_id=version,mention_id=mention.id,field=field)


def _assignments(field,mentions,frames,support):
    n=len(frames)
    if not mentions:return [()]
    choices=[]
    if n==1:
        return [(_field(field,m,frames[0]),) for m in mentions]
    if len(mentions)>=n:
        chosen_sets = [tuple(mentions)] if field=='BENEFICIARY' and len(mentions)==n and len({f.anchor_id for f in frames})==1 else permutations(mentions,n)
        for chosen in chosen_sets:
            choices.append(tuple(_field(field,m,f) for m,f in zip(chosen,frames)))
    else:
        for m in mentions:
            choices.extend((_field(field,m,f),) for f in frames)
            if len(frames)>=2:
                choices.append((claim(SharedFieldClaim,support,
                    depends_on=tuple(frame_dep(f) for f in frames),frame_ids=tuple(f.frame_id for f in frames),mention_id=m.id,field=field,
                    mode='DISTRIBUTIVE' if field in {'AMOUNT','QUANTITY'} else 'CONTEXTUAL'),))
    return choices


def _expression_variants(snapshot,packet):
    mentions={m.id:m for m in snapshot.semantic_mentions}
    used={c.mention_id for c in packet.claims if isinstance(c,(FieldOfClaim,SharedFieldClaim))}
    extras=[]
    for mid in used:
        parent=mentions[mid]
        if parent.role!='dependent_amount':continue
        for child in snapshot.semantic_mentions:
            if child.id==mid or child.role not in {'fraction','percentage'}:continue
            if parent.evidence.start<=child.evidence.start and child.evidence.end<=parent.evidence.end:
                support=(packet.frames[0].anchor_id,)
                extras.append(claim(OperandOfClaim,support,parent_mention_id=mid,operand_mention_id=child.id,
                    parameter='FRACTION' if child.role=='fraction' else 'PERCENTAGE'))
        for a in snapshot.relational_anchors:
            if a.kind not in {'BASIS','REFERENCE'}:continue
            if parent.evidence.start<=a.evidence.start and a.evidence.end<=parent.evidence.end:
                extras.append(claim(RefersToClaim,(a.id,),reference_anchor_id=a.id,carrier_mention_id=mid,
                    requested_field='AMOUNT',antecedent_ids=()))
    if not extras:return (packet,)
    symbolic=Packet(id='',kind=packet.kind+'_SYMBOLIC',frames=packet.frames,claims=packet.claims+tuple(extras))
    # Offer, never force, a distinct interpretation for source-role evidence
    # wholly contained by the selected dependent amount and its basis anchor.
    basis_ids={c.carrier_mention_id for c in extras if isinstance(c,RefersToClaim)}
    basis_sources=set()
    for parent_id in basis_ids:
        parent=mentions[parent_id]
        for m in snapshot.semantic_mentions:
            if m.role!='source_account':continue
            if not (parent.evidence.start<=m.evidence.start and m.evidence.end<=parent.evidence.end):continue
            if any(a.kind=='BASIS' and a.evidence.start<=m.evidence.start and m.evidence.end<=a.evidence.end for a in snapshot.relational_anchors):basis_sources.add(m.id)
    if basis_sources:
        filtered=tuple(c for c in symbolic.claims if not (isinstance(c,(FieldOfClaim,SharedFieldClaim)) and c.field=='SOURCE_ACCOUNT' and c.mention_id in basis_sources))
        return (packet,symbolic,Packet(id='',kind=packet.kind+'_SYMBOLIC_BASIS_ONLY',frames=packet.frames,claims=filtered))
    return (packet,symbolic)


def build_registry(snapshot,*,limits=Limits()):
    digest=content_sha256(snapshot)
    predicates=[a for a in snapshot.relational_anchors if a.kind=='PREDICATE']
    mentions=[m for m in snapshot.semantic_mentions if m.origin=='CANONICAL']
    def stop(status,reason,packets=()):
        return Registry(snapshot_sha256=digest,status=status,reason=reason,
            counts=(('mentions',len(mentions)),('predicates',len(predicates)),('packets',len(packets))))
    if len(mentions)>limits.max_mentions or len(predicates)>limits.max_predicates:
        return stop('LIMIT_EXCEEDED','mention/predicate limit')
    if not predicates:return stop('UNSUPPORTED','ANCHOR_MISSING')
    if snapshot.prior_context:return stop('UNSUPPORTED','prior-context policy deferred in MVP')
    pools={f:[m for m in mentions if m.role in roles] for f,roles in ROLE_FIELDS.items()}
    if any(len(pools[f])>2 for f in ['AMOUNT','BENEFICIARY','DESTINATION_ACCOUNT']):
        return stop('LIMIT_EXCEEDED','more than two target/value occurrences in MVP')
    coordination=[a for a in snapshot.relational_anchors if a.kind=='COORDINATION']
    corrections=[a for a in snapshot.relational_anchors if a.kind=='CORRECTION']
    negations=[a for a in snapshot.relational_anchors if a.kind=='NEGATION']
    skeletons=[tuple(FrameSpec(frame_id='f'+str(i),anchor_id=a.id) for i,a in enumerate(predicates))]
    if len(predicates)==1 and coordination and (len(pools['AMOUNT'])==2 or len(pools['BENEFICIARY'])==2 or len(pools['DESTINATION_ACCOUNT'])==2):
        skeletons.append(tuple(FrameSpec(frame_id='f'+str(i),anchor_id=predicates[0].id) for i in range(2)))
    packets=[];seen=set()
    def add(packet):
        data={p.mention_id for p in snapshot.ping_projection if p.producer_scope=='NESTED_DATA'}
        variants=list(_expression_variants(snapshot,packet))
        for variant in tuple(variants):
            filtered=tuple(c for c in variant.claims if not (isinstance(c,(FieldOfClaim,SharedFieldClaim)) and c.mention_id in data))
            if filtered!=variant.claims:variants.append(Packet(id='',kind=variant.kind+'_DATA_ONLY',frames=variant.frames,claims=filtered))
        for variant in variants:
            signature=content_sha256(variant)
            if signature in seen:continue
            seen.add(signature)
            if len(packets)+2>=limits.max_packets:raise OverflowError('packet count limit')
            packets.append(Packet(id='p'+str(len(packets)),kind=variant.kind,frames=variant.frames,claims=variant.claims))
    try:
        for frames in skeletons:
            support=tuple(f.anchor_id for f in frames)+tuple(a.id for a in coordination)
            menus=[_assignments(field,ms,frames,support) for field,ms in pools.items()]
            upper=1
            for menu in menus:upper*=len(menu)
            if upper+len(packets)+2>limits.max_packets:raise OverflowError('field-assignment product limit')
            group=(claim(CoordinatedClaim,support,depends_on=tuple(frame_dep(f) for f in frames),group_id='coord',frame_ids=tuple(f.frame_id for f in frames)),) if len(frames)>1 and coordination else ()
            for choices in product(*menus):
                add(Packet(id='',kind='BINDING',frames=frames,claims=tuple(c for cs in choices for c in cs)+group))
        # Explicit total vs each ambiguity. No arithmetic, no implicit distribution.
        if len(predicates)==1 and len(pools['AMOUNT'])==1 and len(pools['BENEFICIARY'])==2 and coordination:
            total=FrameSpec(frame_id='total',anchor_id=predicates[0].id)
            per=tuple(FrameSpec(frame_id='per'+str(i),anchor_id=predicates[0].id) for i in range(2))
            frames=(total,*per);support=(predicates[0].id,*[a.id for a in coordination]);amount=pools['AMOUNT'][0]
            fields=[_field('AMOUNT',amount,total),*[_field('BENEFICIARY',m,total) for m in pools['BENEFICIARY']]]
            fields.extend(_field('BENEFICIARY',m,f) for m,f in zip(pools['BENEFICIARY'],per))
            fields.append(claim(SharedFieldClaim,support,depends_on=tuple(frame_dep(f) for f in per),frame_ids=tuple(f.frame_id for f in per),mention_id=amount.id,field='AMOUNT',mode='DISTRIBUTIVE'))
            for field in ['SOURCE_ACCOUNT','DESTINATION_ACCOUNT','CURRENCY','REFERENCE']:
                if len(pools[field])==1:
                    m=pools[field][0];fields.append(_field(field,m,total))
                    fields.append(claim(SharedFieldClaim,support,depends_on=tuple(frame_dep(f) for f in per),frame_ids=tuple(f.frame_id for f in per),mention_id=m.id,field=field,mode='CONTEXTUAL'))
            fields.append(claim(AlternativeClaim,support,depends_on=tuple(frame_dep(f) for f in frames),group_id='allocation',branches=(AlternativeBranch(id='total',frame_ids=(total.frame_id,),allocation='TOTAL_UNALLOCATED'),AlternativeBranch(id='per',frame_ids=tuple(f.frame_id for f in per),allocation='PER_RECIPIENT'))))
            add(Packet(id='',kind='ALLOCATION_UNRESOLVED',frames=frames,claims=tuple(fields)))
        # Corrections are whole packets with explicit carry subsets, not guessed carry.
        bases=[p for p in packets if len(p.frames)==1 and p.kind=='BINDING']
        for base in bases:
            frame=base.frames[0];direct=[c for c in base.claims if isinstance(c,FieldOfClaim)]
            for old in direct:
                if old.field not in {'AMOUNT','SOURCE_ACCOUNT'}:continue
                for new in pools[old.field]:
                    if new.id==old.mention_id:continue
                    for cue in corrections:
                        other=tuple(c.field for c in direct if c.field!=old.field)
                        for n in range(len(other)+1):
                            for carry in combinations(other,n):
                                r=claim(ReplacesClaim,(cue.id,),depends_on=(frame_dep(frame),),target=FieldTarget(frame_id=frame.frame_id,version_id='v0',field=old.field,mention_id=old.mention_id),replacement_frame_id=frame.frame_id,replacement_version_id='v1',carry_fields=carry)
                                changed=_field(old.field,new,frame,version='v1',dep=r.id)
                                add(Packet(id='',kind='CORRECTION_'+old.field,frames=base.frames,claims=base.claims+(r,changed)))
                    if old.field=='SOURCE_ACCOUNT':
                        for cue in negations:
                            rejected=claim(RejectsClaim,(cue.id,),depends_on=(frame_dep(frame),),target=FieldTarget(frame_id=frame.frame_id,version_id='v0',field='SOURCE_ACCOUNT',mention_id=new.id))
                            add(Packet(id='',kind='LOCAL_REJECTION',frames=base.frames,claims=base.claims+(_field('SOURCE_ACCOUNT',new,frame),rejected)))
        ids={f.frame_id for p in packets for f in p.frames}
        if len(ids)>limits.max_frames:raise OverflowError('frame hypothesis limit')
    except OverflowError as e:
        return stop('LIMIT_EXCEEDED',str(e),packets)
    edges={content_sha256(c) for p in packets for c in p.claims}
    return Registry(snapshot_sha256=digest,status='READY',packets=tuple(packets),counts=(('mentions',len(mentions)),('predicates',len(predicates)),('frames',len(ids)),('packets',len(packets)),('primitive_relations',len(edges))))
