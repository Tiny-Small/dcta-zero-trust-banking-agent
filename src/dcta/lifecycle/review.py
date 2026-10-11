"""Exact business PASS replay and deterministic rendering, not semantic inference."""
from dcta.ponder.serialization import content_sha256
from dcta.validation.records import string_hash,json_text
from dcta.business.input import BusinessValidationInput
from dcta.business.records import BusinessValidationResult
from dcta.business.gate import BusinessGate,assess_business_gate
from .records import Review,Transfer
from .errors import LifecycleError


def prepare_review(data,result,gate):
    data=BusinessValidationInput.model_validate(data);result=BusinessValidationResult.model_validate(result);gate=BusinessGate.model_validate(gate)
    expected=assess_business_gate(data,result)
    if gate!=expected or gate.state!='ELIGIBLE_FOR_CONFIRMATION' or result.status!='PASS':raise LifecycleError('BUSINESS_NOT_ELIGIBLE')
    registry={e.id:e for e in data.semantic_input.directory.entities}
    ledger={x.candidate_id:x for x in result.funds_ledger};transfers=[]
    for target in data.targets:
        entry=ledger.get(target.candidate_id)
        if entry is None or not entry.accepted:raise LifecycleError('EXECUTION_PLAN_UNSUPPORTED')
        fields=tuple(f for f in data.grounded_fields if f.candidate_id==target.candidate_id and f.field in ('BENEFICIARY','DESTINATION_ACCOUNT'))
        if len(fields)!=1 or fields[0].status!='RESOLVED':raise LifecycleError('EXECUTION_TARGET_UNSUPPORTED')
        dest=registry[fields[0].selected_entity_id];source=registry[entry.source_account_id]
        transfers.append(Transfer(candidate_id=target.candidate_id,version_id=target.version_id,candidate_sha256=target.candidate_sha256,source_account_id=source.id,source_label=source.name,target_entity_id=dest.id,target_label=dest.name,target_kind=dest.kind,currency=entry.currency,amount=entry.requested))
    # Every supplied field, condition and provenance is part of the rendered payload,
    # including optional reference text. The hash inventory is human-reviewable JSON.
    payload={'notice':'Review this exact mock bundle. Confirmation does not authorize execution.','transfers':[t.model_dump(mode='json') for t in transfers],
        'semantic_fields':[{'candidate_id':x.candidate.id,'version_id':x.candidate.version_id,'bindings':x.candidate.model_dump(mode='json')['bindings'],'mentions':[m.model_dump(mode='json') for m in x.mentions]} for x in data.candidates],
        'conditions':[c.model_dump(mode='json') for c in data.conditions],
        'bindings':{'bundle':data.bundle_sha256,'compilation':data.compilation_sha256,'grounding':data.grounding_sha256,'grounding_revision':data.grounding_revision,'semantic_input':data.semantic_input_sha256,'semantic_decision':data.semantic_decision_sha256,'semantic_gate':data.semantic_gate_sha256,'business_input':content_sha256(data),'business_result':content_sha256(result),'business_gate':content_sha256(gate),'bank':data.bank_sha256,'bank_version':data.bank.version,'bank_revision':data.bank.revision,'policy':data.policy_sha256,'policy_version':data.policy.version}}
    rendered=json_text(payload)
    return Review(data=data,business_result=result,business_gate=gate,transfers=tuple(transfers),rendered_payload=rendered,rendered_payload_sha256=string_hash(rendered))


def verify_review(review):
    if type(review) is not Review or prepare_review(review.data,review.business_result,review.business_gate)!=review:raise LifecycleError('REVIEW_INTEGRITY')
    return review
