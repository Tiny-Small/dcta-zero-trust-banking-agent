"""Independent source-backed comparisons. No extraction or banking service calls."""
import re
from decimal import Decimal,InvalidOperation
from .input import integrity_errors
from dcta.ponder.input import EvidenceRef
from .records import Finding,json_text,string_hash


def finding(data,result,kind,field,reason,*,item=None,proposed='',evidence_ids=('source:full',)):
    evidence={e.id:e.evidence for e in data.evidence}
    source=data.snapshot.current_source
    evidence['source:full']=EvidenceRef(source_id=source.id,start=0,end=len(source.text),text=source.text)
    ids=tuple(e for e in evidence_ids if e in evidence) or ('source:full',)
    return Finding(id='finding:'+string_hash(json_text([result,kind,field,reason,item.candidate.id if item else None,proposed,ids]))[:20],result=result,kind=kind,field=field,
        candidate_id=item.candidate.id if item else None,version_id=item.candidate.version_id if item else None,proposed=proposed,evidence_ids=ids,evidence=tuple(evidence[e] for e in ids),reason=reason)


def source_decimal(text):
    # Compare only the exact supplied span, never discover/select an amount.
    m=re.fullmatch(r'\s*(?:(?:[A-Z]{3}|US\$|S\$|\$)\s*)?([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*',text)
    return Decimal(m[1].replace(',','')) if m else None


def deterministic_findings(data):
    out=[]
    for error in integrity_errors(data):out.append(finding(data,'CONTRACT_ERROR','INPUT_INTEGRITY','INPUT',error))
    if out:return tuple(out)
    if data.producer_status!='OK':return (finding(data,'CONTRACT_ERROR','PRODUCER_STATE','INPUT',data.producer_status),)
    if data.snapshot.input_status!='COMPLETE' or data.snapshot.current_source.finality!='FINAL':out.append(finding(data,'UNRESOLVED','PARTIAL_SOURCE','INPUT','Source is not a complete final snapshot'))
    if data.requested_group_ids:out.append(finding(data,'UNRESOLVED','ALLOCATION_AMBIGUITY','JOINT_BINDINGS','Correlated allocation/group still requires a user branch choice',proposed=json_text([g.model_dump(mode='json') for g in data.groups if g.id in data.requested_group_ids])))
    if data.unresolved_projections:out.append(finding(data,'UNRESOLVED','CURRENT_INTENT_AMBIGUITY','CURRENT_INTENT','Current-intent interpretation remains unresolved'))
    if not data.targets:out.append(finding(data,'UNRESOLVED','NO_CURRENT_TRANSACTION','OPERATION_COUNT','No declared current transaction can progress'))
    active={m.id for item in data.context for m in item.mentions}
    for expr in data.expressions:
        if expr.kind=='UNRESOLVED' and (expr.mention_id is None or expr.mention_id in active):
            out.append(finding(data,'UNRESOLVED','UNRESOLVED_EXPRESSION','AMOUNT','Active symbolic expression is unresolved',proposed=json_text(expr.model_dump(mode='json')),evidence_ids=('mention:'+expr.mention_id,) if expr.mention_id else ('source:full',)))
    for ref in data.unresolved_references:
        if ref.carrier_mention_id is None or ref.carrier_mention_id in active:
            out.append(finding(data,'UNRESOLVED','SYMBOLIC_REFERENCE','AMOUNT',ref.reason,proposed=json_text(ref.model_dump(mode='json')),evidence_ids=('anchor:'+ref.anchor_id,)))
    for issue in data.issues:
        if issue.severity=='ERROR':out.append(finding(data,'CONTRACT_ERROR','REPRESENTATION_ERROR','INPUT',issue.category))
        elif issue.severity=='UNRESOLVED':out.append(finding(data,'UNRESOLVED','REPRESENTATION_UNRESOLVED','INPUT',issue.category))
    for item in data.context:
        c=item.candidate;bindings={b.field:b for b in c.bindings};mentions={m.id:m for m in item.mentions}
        required=('REFERENCE',) if c.goal=='reference_update' else ('ASSET','QUANTITY') if c.goal=='investment' else ('AMOUNT',) if c.goal in {'transfer','payment'} else ()
        if c.goal=='unknown':out.append(finding(data,'UNRESOLVED','UNKNOWN_OPERATION','OPERATION_TYPE','Unknown operation goal',item=item))
        if c.goal=='investment':out.append(finding(data,'UNRESOLVED','INVESTMENT_ACTION_UNREPRESENTED','OPERATION_TYPE','Frozen IR has coarse investment goal but no declared buy/sell action; do not infer it',item=item))
        if c.goal in {'transfer','payment'} and not any(bindings.get(f) and bindings[f].status=='BOUND' and bindings[f].mention_ids for f in ('BENEFICIARY','DESTINATION_ACCOUNT')):
            out.append(finding(data,'UNRESOLVED','MISSING_TARGET','BENEFICIARY','Recipient or destination account is required',item=item))
        for field in required:
            b=bindings.get(field)
            if b is None or b.status!='BOUND' or not b.mention_ids:out.append(finding(data,'UNRESOLVED','MISSING_REQUIRED_FIELD',field,'Required semantic field is absent/unresolved',item=item))
        for b in c.bindings:
            if b.status in {'UNRESOLVED','ALTERNATIVE'} or (b.mention_ids and b.status!='BOUND'):out.append(finding(data,'UNRESOLVED','UNRESOLVED_BINDING',b.field,'Binding remains '+b.status,item=item,proposed=json_text(b.model_dump(mode='json'))))
            for mid in b.mention_ids:
                m=mentions[mid];norm=m.normalized
                if norm is None:continue
                if b.field in {'AMOUNT','QUANTITY'} and norm.kind=='decimal':
                    literal=source_decimal(m.evidence.text)
                    if literal is not None:
                        try:valid=Decimal(norm.value).is_finite() and literal==Decimal(norm.value)
                        except InvalidOperation:valid=False
                        if not valid:out.append(finding(data,'DISCREPANCY','SCALAR_VALUE_MISMATCH',b.field,'Proposed scalar differs from the exact source span',item=item,proposed=norm.value,evidence_ids=('mention:'+mid,)))
                elif norm.kind=='text' and norm.value.strip()!=m.evidence.text.strip():out.append(finding(data,'DISCREPANCY','LITERAL_VALUE_MISMATCH',b.field,'Proposed text differs from the exact user reference',item=item,proposed=norm.value,evidence_ids=('mention:'+mid,)))
                elif b.field=='CURRENCY':
                    expected={'S$':'SGD','US$':'USD'}.get(m.evidence.text.upper(),m.evidence.text.upper())
                    if norm.value.upper()!=expected:out.append(finding(data,'DISCREPANCY','CURRENCY_MISMATCH',b.field,'Currency code not supported by the literal source symbol/code',item=item,proposed=norm.value,evidence_ids=('mention:'+mid,)))
        if data.grounding:
            for b in c.bindings:
                if b.field in {'BENEFICIARY','SOURCE_ACCOUNT','DESTINATION_ACCOUNT','ASSET'} and b.status=='BOUND':
                    for mid in b.mention_ids:
                        if not any(f.candidate_id==c.id and f.field==b.field and f.mention_id==mid for f in data.grounding.fields):out.append(finding(data,'UNRESOLVED','MISSING_GROUNDING',b.field,'No version-bound grounding result for supplied reference',item=item,evidence_ids=('mention:'+mid,)))
    if data.grounding:
        items={x.candidate.id:x for x in data.context}
        for f in data.grounding.fields:
            item=items[f.candidate_id]
            if f.status!='RESOLVED':
                kind='ENTITY_AMBIGUITY' if f.status=='AMBIGUOUS' else 'ENTITY_NOT_FOUND' if f.status=='NOT_FOUND' else 'SYMBOLIC_REFERENCE'
                out.append(finding(data,'UNRESOLVED',kind,f.field,'Grounding remains '+f.status,item=item,proposed=json_text(f.model_dump(mode='json')),evidence_ids=('mention:'+f.mention_id,)));continue
            selected=next((e for e in f.matches if e.id==f.selected_entity_id),None)
            if selected is None:out.append(finding(data,'CONTRACT_ERROR','MALFORMED_GROUNDING',f.field,'Selected entity is not in supplied matches',item=item));continue
            aliases={x.strip().casefold() for x in (selected.name,*selected.aliases)}
            if f.literal.strip().casefold() not in aliases:out.append(finding(data,'DISCREPANCY','ENTITY_REFERENCE_MISMATCH',f.field,'Selected grounded entity is unsupported by the literal user reference',item=item,proposed=selected.name,evidence_ids=('mention:'+f.mention_id,)))
    if not out:
        from .semantic import build_request
        try:build_request(data)
        except OverflowError:out.append(finding(data,'UNRESOLVED','LIMIT_EXCEEDED','INPUT','Bounded independent observation cannot assess this input'))
    return tuple(out)
