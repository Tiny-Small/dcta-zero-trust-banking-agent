"""Pure gate: replay the retained observation; never authorize or execute."""
from typing import Literal
from pydantic import model_validator
from dcta.ponder.base import FrozenRecord
from dcta.ponder.serialization import content_sha256
from .input import ValidationInput
from .records import ValidationDecision,ValidationTarget,Finding,Result,VERSION
from .engine import finalize
from .checks import finding


class FreezeGate(FrozenRecord):
    schema_version: Literal['semantic-freeze-gate-v1']='semantic-freeze-gate-v1'
    state: Literal['FROZEN','ELIGIBLE_FOR_BUSINESS_CHECKS']
    result: Result
    targets: tuple[ValidationTarget,...]
    validation_input_sha256: str
    validation_decision_sha256: str | None
    observation_sha256: str | None
    grounding_sha256: str | None
    grounding_revision: int | None
    findings: tuple[Finding,...]
    execution_authorized: Literal[False]=False

    @model_validator(mode='after')
    def eligibility_integrity(self):
        if (self.state=='ELIGIBLE_FOR_BUSINESS_CHECKS')!=(self.result=='MATCH'):
            raise ValueError('Gate state must agree with exact validation result')
        if self.result=='MATCH':
            if not self.targets or not self.validation_decision_sha256 or not self.observation_sha256 or self.findings:
                raise ValueError('MATCH requires exact targets, decision/observation hashes and no findings')
        elif not self.findings:
            raise ValueError('Every frozen result requires explicit findings')
        return self


def assess_gate(data,decision,*,candidate_id=None):
    # Typed input is required; malformed external input must fail at this boundary.
    # The gate cannot supply missing source/provenance to repair a malformed input.
    data=ValidationInput.model_validate(data)
    result='CONTRACT_ERROR';findings=();dh=None;oh=None
    targets=tuple(ValidationTarget(candidate_id=x.candidate.id,frame_id=x.candidate.frame_id,version_id=x.candidate.version_id,candidate_sha256=content_sha256(x.candidate)) for x in data.targets)
    try:
        decision=ValidationDecision.model_validate(decision);dh=content_sha256(decision);oh=content_sha256(decision.observation)
        replay=finalize(data,decision.observation)
        if decision.validator_version!=VERSION or decision!=replay:
            raise ValueError('Stale, cross-version or altered validation decision; exact local observation replay failed')
        if candidate_id is not None and candidate_id not in {t.candidate_id for t in targets}:
            raise ValueError('Validation cannot attach to another candidate/operation')
        result=decision.result;findings=decision.findings
    except (ValueError,TypeError,AttributeError,KeyError) as error:
        findings=(finding(data,'CONTRACT_ERROR','GATE_DECISION_INTEGRITY','INPUT',str(error)),)
    return FreezeGate(state='ELIGIBLE_FOR_BUSINESS_CHECKS' if result=='MATCH' else 'FROZEN',result=result,targets=targets,
        validation_input_sha256=content_sha256(data),validation_decision_sha256=dh,observation_sha256=oh,
        grounding_sha256=data.grounding_sha256,grounding_revision=data.grounding_revision,findings=findings)
