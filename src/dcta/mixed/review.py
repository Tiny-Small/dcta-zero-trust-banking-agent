"""Complete mixed review: both domains/actions and every gate/version are bound."""
from typing import Literal
from dcta.ponder.base import FrozenRecord
from dcta.ponder.serialization import content_sha256
from dcta.validation.records import json_text,string_hash
from dcta.lifecycle.records import Transfer
from dcta.lifecycle.errors import LifecycleError
from .business import MixedBusinessInput,MixedBusinessResult,InvestmentPlan,validate_business

class MixedBusinessGate(FrozenRecord):
    schema_version: Literal['mixed-business-gate-v1']='mixed-business-gate-v1'
    state: Literal['ELIGIBLE_FOR_CONFIRMATION','NEEDS_CLARIFICATION','BLOCKED','CONTRACT_ERROR']
    input_sha256: str
    result_sha256: str

class MixedReview(FrozenRecord):
    schema_version: Literal['mixed-exact-bundle-review-v1']='mixed-exact-bundle-review-v1'
    data: MixedBusinessInput
    business_result: MixedBusinessResult
    business_gate: MixedBusinessGate
    transfers: tuple[Transfer,...]
    investment: InvestmentPlan
    rendered_payload: str
    rendered_payload_sha256: str


def assess_business_gate(data,result):
    state='CONTRACT_ERROR' if validate_business(data)!=result else 'ELIGIBLE_FOR_CONFIRMATION' if result.status=='PASS' else result.status
    return MixedBusinessGate(state=state,input_sha256=content_sha256(data),result_sha256=content_sha256(result))


def prepare_review(data,result):
    data=MixedBusinessInput.model_validate(data);result=MixedBusinessResult.model_validate(result);gate=assess_business_gate(data,result)
    if gate.state!='ELIGIBLE_FOR_CONFIRMATION' or result.investment is None:raise LifecycleError('MIXED_BUSINESS_NOT_ELIGIBLE')
    registry={e.id:e for e in data.semantic_input.directory.entities};ledger={e.candidate_id:e for e in result.funds_ledger};transfers=[]
    for item,target in zip(data.candidates,data.targets):
        if item.candidate.goal=='investment':continue
        entry=ledger.get(target.candidate_id)
        fields=[f for f in data.grounded_fields if f.candidate_id==target.candidate_id and f.field in {'BENEFICIARY','DESTINATION_ACCOUNT'}]
        if entry is None or not entry.accepted or len(fields)!=1 or fields[0].status!='RESOLVED':raise LifecycleError('MIXED_EXECUTION_PLAN_UNSUPPORTED')
        source=registry[entry.source_account_id];dest=registry[fields[0].selected_entity_id]
        transfers.append(Transfer(candidate_id=target.candidate_id,version_id=target.version_id,candidate_sha256=target.candidate_sha256,source_account_id=source.id,source_label=source.name,target_entity_id=dest.id,target_label=dest.name,target_kind=dest.kind,currency=entry.currency,amount=entry.requested))
    if len(transfers)!=1:raise LifecycleError('MIXED_MONETARY_TOPOLOGY')
    inv=result.investment;rows={inv.candidate_id:{'goal':'investment',**inv.model_dump(mode='json')}}
    for t in transfers:
        item=next(x for x in data.candidates if x.candidate.id==t.candidate_id);rows[t.candidate_id]={'goal':item.candidate.goal,**t.model_dump(mode='json')}
    payload={'notice':'Review this exact mock mixed bundle. Confirmation does not authorize. Investment is a synthetic order simulation: no price, funding, cash settlement or real trade.',
        'operations':[rows[x.candidate.id] for x in data.candidates],
        'semantic_fields':[x.model_dump(mode='json') for x in data.candidates],
        'conditions':[c.model_dump(mode='json') for c in data.conditions],
        'bindings':{'bundle':data.bundle_sha256,'interpretation':content_sha256(data.semantic.interpretation),'compilation':data.semantic.core.compilation_sha256,'mixed_relations':content_sha256(data.semantic.interpretation.relations),
        'grounding':data.semantic.core.grounding_sha256,'grounding_revision':data.semantic.core.grounding_revision,'semantic_input':content_sha256(data.semantic),'semantic_decision':content_sha256(data.decision),'semantic_gate':content_sha256(data.gate),
        'business_input':content_sha256(data),'business_result':content_sha256(result),'business_gate':content_sha256(gate),'bank':data.bank_sha256,'bank_version':data.bank.version,'bank_revision':data.bank.revision,
        'bank_policy':data.policy_sha256,'bank_policy_version':data.policy.version,'investment_state':content_sha256(data.investment_state),'investment_policy':content_sha256(data.investment_policy),'investment_policy_version':data.investment_policy.version}}
    rendered=json_text(payload)
    return MixedReview(data=data,business_result=result,business_gate=gate,transfers=tuple(transfers),investment=inv,rendered_payload=rendered,rendered_payload_sha256=string_hash(rendered))


def verify_review(review):
    if type(review) is not MixedReview or prepare_review(review.data,review.business_result)!=review:raise LifecycleError('MIXED_REVIEW_INTEGRITY')
    return review
