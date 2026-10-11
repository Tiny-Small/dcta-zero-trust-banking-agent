"""Replay-bound banking gate. Eligibility is not confirmation/authorization."""
from typing import Literal
from pydantic import model_validator
from dcta.ponder.base import FrozenRecord
from dcta.ponder.serialization import content_sha256
from dcta.validation.records import ValidationTarget
from .input import BusinessValidationInput
from .records import BusinessValidationResult,BusinessFinding,Status
from .engine import validate_business
from .checks import finding,combine

STATES={'PASS':'ELIGIBLE_FOR_CONFIRMATION','NEEDS_CLARIFICATION':'NEEDS_CLARIFICATION','BLOCKED':'BLOCKED','CONTRACT_ERROR':'CONTRACT_ERROR'}

class BusinessGate(FrozenRecord):
    schema_version: Literal['business-gate-v1']='business-gate-v1'
    state: Literal['ELIGIBLE_FOR_CONFIRMATION','NEEDS_CLARIFICATION','BLOCKED','CONTRACT_ERROR']
    status: Status
    targets: tuple[ValidationTarget,...]
    business_input_sha256: str
    business_result_sha256: str | None
    bundle_sha256: str
    compilation_sha256: str
    grounding_sha256: str | None
    grounding_revision: int | None
    semantic_input_sha256: str
    semantic_decision_sha256: str
    semantic_gate_sha256: str
    bank_sha256: str
    bank_version: str
    bank_revision: int
    policy_sha256: str
    policy_version: str
    findings: tuple[BusinessFinding,...]
    confirmed: Literal[False]=False
    authorized: Literal[False]=False
    executable: Literal[False]=False

    @model_validator(mode='after')
    def eligibility_integrity(self):
        if self.state!=STATES[self.status] or not self.findings or combine(f.result for f in self.findings)!=self.status:
            raise ValueError('Business gate state/status/findings disagree')
        if self.status=='PASS' and (not self.targets or not self.business_result_sha256 or not self.business_input_sha256 or not self.semantic_gate_sha256 or not self.bank_sha256 or not self.policy_sha256):
            raise ValueError('Eligibility requires exact targets and complete result/input/semantic/state/policy provenance')
        return self


def assess_business_gate(data,result,*,candidate_id=None):
    data=BusinessValidationInput.model_validate(data);status='CONTRACT_ERROR';rh=None
    try:
        result=BusinessValidationResult.model_validate(result);rh=content_sha256(result)
        if result!=validate_business(data):raise ValueError('Stale/mismatched/tampered business result; exact deterministic replay failed')
        if candidate_id is not None and candidate_id not in {t.candidate_id for t in data.targets}:raise ValueError('Business result cannot attach to another operation')
        status=result.status;findings=(*result.findings,*(f for op in result.operations for f in op.findings))
    except (ValueError,TypeError,AttributeError,KeyError) as error:
        findings=(finding(data,'CONTRACT_ERROR','BUSINESS_GATE_INTEGRITY','INPUT',str(error),'Exact reviewed candidate/bank/policy/result required'),)
    return BusinessGate(state=STATES[status],status=status,targets=data.targets,business_input_sha256=content_sha256(data),business_result_sha256=rh,bundle_sha256=data.bundle_sha256,
        compilation_sha256=data.compilation_sha256,grounding_sha256=data.grounding_sha256,grounding_revision=data.grounding_revision,semantic_input_sha256=data.semantic_input_sha256,
        semantic_decision_sha256=data.semantic_decision_sha256,semantic_gate_sha256=data.semantic_gate_sha256,bank_sha256=data.bank_sha256,bank_version=data.bank.version,bank_revision=data.bank.revision,
        policy_sha256=data.policy_sha256,policy_version=data.policy.version,findings=tuple(findings))
