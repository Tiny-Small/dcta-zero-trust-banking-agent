"""Pure banking checks against exact fields and explicitly supplied mock state."""
import re
from decimal import localcontext
from dcta.ponder.serialization import content_sha256
from dcta.validation.records import json_text,string_hash
from dcta.validation.checks import source_decimal
from .input import decimal_record
from .records import BusinessFinding,ClarificationRequirement,OperationBusinessResult

PRIORITY={'PASS':0,'NEEDS_CLARIFICATION':1,'BLOCKED':2,'CONTRACT_ERROR':3}


def combine(statuses):return max(statuses,key=PRIORITY.get,default='PASS')


def finding(data,status,code,field,observed,explanation,*,item=None,records=(),record_ids=()):
    mids={m.id:m for m in item.mentions} if item else {}
    evidence=tuple(mids[mid].evidence for b in item.candidate.bindings if b.field==field for mid in b.mention_ids) if item else ()
    if not evidence:
        source=data.semantic_input.snapshot.current_source
        from dcta.ponder.input import EvidenceRef
        evidence=(EvidenceRef(source_id=source.id,start=0,end=len(source.text),text=source.text),)
    mock_json=json_text([r.model_dump(mode='json') for r in records])
    return BusinessFinding(candidate_id=item.candidate.id if item else None,version_id=item.candidate.version_id if item else None,candidate_sha256=content_sha256(item.candidate) if item else None,
        field=field,rule_id=data.policy.version+':'+code,code=code,result=status,observed=str(observed),explanation=explanation,semantic_evidence=evidence,
        mock_record_ids=tuple(record_ids),mock_evidence_json=mock_json,mock_evidence_sha256=string_hash(mock_json),bank_sha256=data.bank_sha256,policy_sha256=data.policy_sha256,semantic_decision_sha256=data.semantic_decision_sha256)


def exact_scale(amount,minor_units):
    digits=list(amount.as_tuple().digits);exponent=amount.as_tuple().exponent
    while digits and digits[-1]==0 and exponent<0:digits.pop();exponent+=1
    return exponent>=-minor_units


def check_operation(data,item,target):
    c=item.candidate;bank=data.bank;policy=data.policy
    bindings={b.field:b for b in c.bindings};mentions={m.id:m for m in item.mentions}
    findings=[];clarifications=[]
    def add(status,code,field,value,message,records=(),ids=()):
        findings.append(finding(data,status,code,field,value,message,item=item,records=records,record_ids=ids))
    def clarify(field,reason,prompt,choices=()):
        clarifications.append(ClarificationRequirement(candidate_id=c.id,version_id=c.version_id,field=field,reason=reason,prompt=prompt,choices=tuple(choices)))
    def single(field):
        b=bindings[field]
        return mentions[b.mention_ids[0]] if b.status=='BOUND' and len(b.mention_ids)==1 else None
    def grounded(field,m):
        return next((f for f in data.grounded_fields if f.candidate_id==c.id and f.field==field and f.mention_id==m.id),None) if m else None
    if c.goal not in policy.supported_goals:
        add('BLOCKED','OPERATION_UNSUPPORTED','OPERATION_TYPE',c.goal,'This monetary banking flow supports only declared transfer/payment operations')
        return OperationBusinessResult(target=target,status='BLOCKED',findings=tuple(findings)),None

    currency=None;m=single('CURRENCY')
    # Read only an explicit ISO span. Symbol-only data is never a default code.
    if m and re.fullmatch(r'[A-Za-z]{3}',m.evidence.text.strip()):currency=m.evidence.text.strip().upper()
    if currency is None:
        add('NEEDS_CLARIFICATION','CURRENCY_REQUIRED','CURRENCY',m.evidence.text if m else '', 'An explicit ISO currency is required; no symbol/account-based default')
        clarify('CURRENCY','CURRENCY_REQUIRED','Which currency did you mean?',(r.iso for r in policy.currencies))
    rule=next((r for r in policy.currencies if r.iso==currency),None)
    if currency is not None:
        if rule is None:add('BLOCKED','CURRENCY_UNSUPPORTED','CURRENCY',currency,'ISO currency is not supported by the mock policy',records=(policy,))
        else:add('PASS','CURRENCY_SUPPORTED','CURRENCY',currency,'Explicit supported ISO currency',records=(rule,))

    amount=None;m=single('AMOUNT')
    if m and m.role!='dependent_amount':
        amount=decimal_record(m.normalized.value) if m.normalized and m.normalized.kind=='decimal' else source_decimal(m.evidence.text) if len(m.evidence.text)<=80 else None
    if amount is None:
        add('NEEDS_CLARIFICATION','AMOUNT_NOT_SCALAR','AMOUNT',m.evidence.text if m else '', 'A usable scalar is required; symbolic bases are not implicitly calculated')
        clarify('AMOUNT','AMOUNT_NOT_SCALAR','What exact amount should be used?')
    else:
        if amount<=0:add('BLOCKED','AMOUNT_NOT_POSITIVE','AMOUNT',amount,'Monetary amount must be positive')
        else:add('PASS','AMOUNT_POSITIVE','AMOUNT',amount,'Positive finite source-backed scalar')
        if rule:
            if not exact_scale(amount,rule.minor_units):add('BLOCKED','AMOUNT_PRECISION','AMOUNT',amount,'Value cannot be represented exactly at the supported currency precision; no rounding',records=(rule,))
            else:add('PASS','AMOUNT_PRECISION_SUPPORTED','AMOUNT',amount,'Exact currency precision; no rounding required',records=(rule,))
            if amount>decimal_record(rule.per_transaction_limit):add('BLOCKED','PER_TRANSACTION_LIMIT','AMOUNT',amount,'Amount exceeds the explicit per-transaction cap',records=(rule,))
            else:add('PASS','WITHIN_TRANSACTION_LIMIT','AMOUNT',amount,'Amount within explicit per-transaction cap',records=(rule,))

    source=None;balance=None;sm=single('SOURCE_ACCOUNT');sf=grounded('SOURCE_ACCOUNT',sm)
    if sf is None or sf.status!='RESOLVED' or not sf.selected_entity_id:
        add('NEEDS_CLARIFICATION','SOURCE_REQUIRED','SOURCE_ACCOUNT',sm.evidence.text if sm else '', 'An explicitly resolved funding source is required; no primary-account default')
        clarify('SOURCE_ACCOUNT','SOURCE_REQUIRED','Which source account should fund this operation?',(a.entity_id for a in bank.accounts if a.owner_id==bank.authenticated_user_id and a.active and a.usable))
    else:
        source=next((a for a in bank.accounts if a.entity_id==sf.selected_entity_id),None)
        if source is None:add('BLOCKED','SOURCE_ACCOUNT_UNSUPPORTED','SOURCE_ACCOUNT',sf.selected_entity_id,'No supported supplied banking record for the grounded source')
        else:
            for valid,code,message in [(source.owner_id==bank.authenticated_user_id,'SOURCE_NOT_OWNED','Source must belong to the mock authenticated user'),(source.active,'SOURCE_INACTIVE','Source must be active'),(source.usable,'SOURCE_UNUSABLE','Source must be usable')]:
                add('PASS' if valid else 'BLOCKED',code+'_CHECKED' if valid else code,'SOURCE_ACCOUNT',source.entity_id,message,records=(source,),ids=(source.entity_id,bank.authenticated_user_id))
            if currency:
                if currency not in source.supported_currencies:add('BLOCKED','SOURCE_CURRENCY_UNSUPPORTED','SOURCE_ACCOUNT',currency,'Source does not support this explicit currency; no FX conversion',records=(source,),ids=(source.entity_id,))
                else:
                    balance=next((b for b in source.balances if b.currency==currency),None)
                    if balance is None:add('NEEDS_CLARIFICATION','BALANCE_UNAVAILABLE','SOURCE_ACCOUNT',currency,'Trusted available-funds observation is missing',records=(source,),ids=(source.entity_id,))
                    elif amount is not None and amount>0:
                        available=decimal_record(balance.available)
                        add('PASS' if amount<=available else 'BLOCKED','FUNDS_AVAILABLE' if amount<=available else 'INSUFFICIENT_FUNDS','AMOUNT',amount,'Compare requested amount to supplied available funds; never change amount',records=(source,balance),ids=(source.entity_id,bank.snapshot_id))

    target_present=False
    for field in ('BENEFICIARY','DESTINATION_ACCOUNT'):
        m=single(field)
        if m is None:continue
        target_present=True;gf=grounded(field,m)
        if gf is None or gf.status!='RESOLVED' or not gf.selected_entity_id:
            add('NEEDS_CLARIFICATION','TARGET_UNRESOLVED',field,m.evidence.text,'Recipient/destination must be explicitly resolved')
            clarify(field,'TARGET_UNRESOLVED','Which intended recipient or destination should be used?');continue
        record=next((r for r in (bank.recipients if field=='BENEFICIARY' else bank.accounts) if (r.entity_id==gf.selected_entity_id)),None)
        if record is None:add('BLOCKED','TARGET_UNSUPPORTED',field,gf.selected_entity_id,'No supported supplied banking record for target');continue
        active=record.active and (record.usable if field=='DESTINATION_ACCOUNT' else True)
        if not active:add('BLOCKED','TARGET_INACTIVE',field,record.entity_id,'Target banking record is inactive/unusable',records=(record,),ids=(record.entity_id,))
        elif currency and currency not in record.supported_currencies:add('BLOCKED','TARGET_CURRENCY_UNSUPPORTED',field,currency,'Target does not support this explicit currency',records=(record,),ids=(record.entity_id,))
        else:add('PASS','TARGET_SUPPORTED',field,record.entity_id,'Grounded target has an active supported mock record',records=(record,),ids=(record.entity_id,))
    if not target_present:
        add('NEEDS_CLARIFICATION','TARGET_REQUIRED','BENEFICIARY','','A beneficiary or destination is required')
        clarify('BENEFICIARY','TARGET_REQUIRED','Who or which destination should receive this transfer?')

    conditions=[x for x in data.conditions if x.candidate_id==c.id]
    for condition in conditions:
        fact=next((f for f in bank.conditions if f.candidate_id==c.id and f.anchor_id==condition.anchor_id),None)
        if fact and (fact.candidate_sha256!=condition.candidate_sha256 or fact.anchor_sha256!=condition.anchor_sha256):
            add('CONTRACT_ERROR','CONDITION_PROVENANCE_MISMATCH','CONDITIONS',condition.anchor_id,'Condition fact belongs to another candidate/version/anchor',records=(fact,),ids=(fact.source_id,));continue
        if fact is None or fact.state=='UNKNOWN':
            add('NEEDS_CLARIFICATION','CONDITION_UNRESOLVED','CONDITIONS',condition.evidence.text,'Condition has not been established by trusted supplied state')
            clarify('CONDITIONS','CONDITION_UNRESOLVED','Please resolve the condition through a new explicit instruction or trusted condition update.');continue
        if (fact.source_id,fact.source_version) not in {(s.id,s.version) for s in policy.trusted_condition_sources}:
            add('NEEDS_CLARIFICATION','CONDITION_UNTRUSTED','CONDITIONS',condition.evidence.text,'Condition source/version is not policy-trusted',records=(fact,),ids=(fact.source_id,));continue
        add('PASS' if fact.state=='SATISFIED' else 'BLOCKED','CONDITION_SATISFIED' if fact.state=='SATISFIED' else 'CONDITION_NOT_SATISFIED','CONDITIONS',condition.evidence.text,'Use exact supplied trusted condition state; no language evaluation',records=(fact,),ids=(fact.source_id,))
    if not conditions:add('PASS','NO_CONDITION','CONDITIONS','','No preserved condition requires evaluation')
    op=OperationBusinessResult(target=target,status=combine(f.result for f in findings),findings=tuple(findings),clarifications=tuple(clarifications))
    funding=(source,currency,amount,balance) if source and currency and amount is not None and amount>0 and balance else None
    return op,funding


def aggregate_funds(data,operations,fundings):
    from .records import FundsLedgerEntry
    operations=list(operations);remaining={};ledger=[];failed=set()
    # Canonical candidate-ID order; record tables are semantically unordered.
    with localcontext() as context:
        context.prec=200
        for n,f in sorted(enumerate(fundings),key=lambda pair:data.targets[pair[0]].candidate_id):
            if not f:continue
            source,currency,amount,balance=f;key=(source.entity_id,currency)
            before=remaining.setdefault(key,decimal_record(balance.available));accepted=amount<=before
            after=before-amount if accepted else before;remaining[key]=after
            ledger.append(FundsLedgerEntry(candidate_id=data.candidates[n].candidate.id,source_account_id=source.entity_id,currency=currency,requested=str(amount),before=str(before),after=str(after),accepted=accepted))
            if not accepted:failed.add(key)
    for n,f in enumerate(fundings):
        if f and (f[0].entity_id,f[1]) in failed:
            op=operations[n];extra=finding(data,'BLOCKED','BUNDLE_INSUFFICIENT_FUNDS','AMOUNT',f[2],'Temporary bundle ledger cannot fund every operation; entire bundle blocked without reservation',item=data.candidates[n],records=(f[0],f[3],*ledger),record_ids=(f[0].entity_id,data.bank.snapshot_id))
            operations[n]=OperationBusinessResult(target=op.target,status=combine([op.status,'BLOCKED']),findings=(*op.findings,extra),clarifications=op.clarifications)
    return tuple(operations),tuple(ledger)


def velocity_findings(data,fundings):
    history=tuple(h for h in data.bank.history if h.day==data.bank.business_day and h.user_id==data.bank.authenticated_user_id)
    findings=[];count=len(history)+len(data.candidates)
    findings.append(finding(data,'PASS' if count<=data.policy.daily_transaction_count_limit else 'BLOCKED','DAILY_COUNT_CHECKED' if count<=data.policy.daily_transaction_count_limit else 'DAILY_COUNT_LIMIT','BUNDLE',count,'Trusted daily completed outgoing count plus all proposed operations',records=(*history,data.policy)))
    with localcontext() as context:
        context.prec=200
        for rule in data.policy.currencies:
            total=sum((decimal_record(h.amount) for h in history if h.currency==rule.iso),start=decimal_record('0'))+sum((f[2] for f in fundings if f and f[1]==rule.iso),start=decimal_record('0'))
            ok=total<=decimal_record(rule.daily_outgoing_limit)
            findings.append(finding(data,'PASS' if ok else 'BLOCKED','DAILY_OUTGOING_CHECKED' if ok else 'DAILY_OUTGOING_LIMIT','BUNDLE',str(total),'Trusted daily outgoing across all source accounts plus complete proposed bundle, per currency; no FX',records=(*history,rule),record_ids=(data.bank.business_day,)))
    return tuple(findings)
