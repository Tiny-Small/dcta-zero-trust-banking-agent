"""Run exact frozen extraction and copy its supplied semantics; no repair."""
import hashlib,json
from pathlib import Path
from dcta.ponder.input import (SourceSnapshot,SemanticMention,EvidenceRef,NormalizedValue,
    CandidateProvenance,PingProjection,RetainedCompound,UpstreamDiagnostic,PonderInputSnapshot)
from .anchors import discover_anchors
from ._extractor.candidate_role_diagnostic import select_candidate_roles
from ._extractor.canonical_diagnostic import canonicalize,resolve_scope


def extractor_hash():
    root=Path(__file__).parent/'_extractor'
    values=[(str(p.relative_to(root)),hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(root.rglob('*.py'))]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def extract_text(text,provider,*,source_id='mvp-input'):
    raw=select_candidate_roles(text,provider=provider,mode='batched')
    result={'id':source_id,'text':text,'raw':raw}
    if raw['stopped']:raise ValueError('upstream candidate-role failure')
    row={'id':source_id,'text':text,'result':raw}
    canonical=canonicalize(row,provider=provider);result['canonical']=canonical
    if canonical['stopped']:raise ValueError('upstream canonical failure')
    scoped=resolve_scope(row,canonical,provider=provider);result['scope']=scoped
    if scoped['stopped']:raise ValueError('upstream scope failure')
    return result


def snapshot_from_extraction(stages,*,source_id=None):
    for key in ('raw','canonical','scope'):
        if not isinstance(stages.get(key),dict) or stages[key].get('stopped'):
            raise ValueError('upstream missing/failed '+key)
    source=SourceSnapshot.from_text(source_id or stages['id'],stages['text'])
    metadata={c['candidate_id']:c for c in stages['raw'].get('candidates',[])}
    canonical=stages['canonical'];scope=stages['scope']
    compound=canonical.get('structural_provenance',{}).get('compounds',[])
    rows=[(s,'CANONICAL') for s in canonical['slots']]+[(c['slot'],'RETAINED_COMPOUND') for c in compound]
    mentions=[];by_cid={};seen=set();retained=[];diagnostics=[]
    for s,origin in rows:
        e=s['evidence'];key=(s['role'],s['candidate_id'],e['start'],e['end'])
        if key in seen:continue
        seen.add(key)
        if type(e['start']) is not int or type(e['end']) is not int or not 0<=e['start']<e['end']<=len(source.text) or source.text[e['start']:e['end']]!=e['text']:
            raise ValueError('invalid supplied financial span')
        mid='m:'+s['role']+':'+s['candidate_id'];c=metadata.get(s['candidate_id'],{})
        norm=s.get('normalized')
        normalized=NormalizedValue(kind=norm['kind'],value=norm['value']) if norm and norm.get('value') is not None else None
        mentions.append(SemanticMention(id=mid,candidate_id=s['candidate_id'],role=s['role'],
            evidence=EvidenceRef(source_id=source.id,**e),normalized=normalized,origin=origin,
            provenance=CandidateProvenance(candidate_types=tuple(c.get('candidate_types',s.get('candidate_types',()))),
                generators=tuple(c.get('generators',s.get('generators',()))),
                producer_record_hash=hashlib.sha256(json.dumps(s,sort_keys=True).encode()).hexdigest())))
        by_cid[s['candidate_id']]=mid
        if origin=='RETAINED_COMPOUND':retained.append(RetainedCompound(mention_id=mid))
    surviving={s['candidate_id'] for s in scope['slots']}
    projections=[]
    for m in mentions:
        links=[r for r in scope.get('scope_relations',[]) if r['inner']['candidate']['candidate_id']==m.candidate_id]
        blocked=[r for r in links if r.get('error_class') or r.get('status') in {'NONE','NESTED_DATA'}]
        relation=blocked[0] if blocked else links[0] if links else None
        parent=by_cid.get(relation['outer']['candidate']['candidate_id']) if relation else None
        status=relation.get('status') if relation else None
        emitted=m.candidate_id in surviving and m.origin=='CANONICAL'
        scope_name='NESTED_DATA' if status=='NESTED_DATA' else 'EXCLUDED_BY_SCOPE' if blocked else 'ROOT_EMITTED' if emitted else 'UNKNOWN'
        projections.append(PingProjection(mention_id=m.id,producer_scope=scope_name,emitted_root=emitted,
            parent_mention_id=parent,scope_decision=status,support_ids=tuple(r['pair_id'] for r in links)))
        if m.origin=='RETAINED_COMPOUND':
            diagnostics.append(UpstreamDiagnostic(id='retained:'+m.id,category='RETAINED_COMPOUND_NOT_ROOT',affected_ids=(m.id,)))
    return PonderInputSnapshot(current_source=source,semantic_mentions=tuple(mentions),ping_projection=tuple(projections),
        relational_anchors=discover_anchors(source),retained_compounds=tuple(retained),upstream_diagnostics=tuple(diagnostics),
        extractor_identity='frozen-parser-jev-post-structural',extractor_sha256=extractor_hash(),contract_version='contract-v2')
