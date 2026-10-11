"""Text-mode DEV orchestration. All semantic judgments remain upstream decisions."""
import json
from typing import Literal
from uuid import uuid4
from dcta.ponder.base import FrozenRecord
from dcta.ponder.ir import PonderCompilation
from dcta.ponder.serialization import content_sha256
from dcta.ponder_mvp.pipeline import assemble_text
from dcta.ponder_mvp.demo import StopRun
from dcta.ponder_mvp.consumer import consume
from dcta.ponder_mvp.grounding import GroundingState,mock_directory,ground,clarify
from dcta.validation.input import ValidationInput,build_input
from dcta.validation.records import ValidationDecision,string_hash,json_text
from dcta.validation.gate import FreezeGate,assess_gate
from dcta.validation.engine import validate
from dcta.business.input import BusinessValidationInput,build_business_input
from dcta.business.records import BusinessValidationResult
from dcta.business.gate import BusinessGate,assess_business_gate
from dcta.business.engine import validate_business
from .records import Review
from .review import prepare_review
from .errors import LifecycleError

class LifecycleState(FrozenRecord):
    status: Literal['UPSTREAM_STOP','NEEDS_GROUNDING','SEMANTIC_FROZEN','NEEDS_CLARIFICATION','BLOCKED','CONTRACT_ERROR','READY_FOR_CONFIRMATION']
    compilation: PonderCompilation | None=None
    grounding: GroundingState | None=None
    grounding_parents: tuple[GroundingState,...]=()
    semantic_input: ValidationInput | None=None
    semantic_input_sha256: str | None=None
    semantic_decision: ValidationDecision | None=None
    semantic_gate: FreezeGate | None=None
    business_input: BusinessValidationInput | None=None
    business_result: BusinessValidationResult | None=None
    business_gate: BusinessGate | None=None
    review: Review | None=None
    last_event_sha256: str
    raw_pipeline_json: str | None=None
    reason: str=''

class TextLifecycle:
    def __init__(self,provider,gateway):
        self.provider=provider;self.gateway=gateway;self.directory=mock_directory();self._current=None
    def _event(self,kind,outcome,records,causes=()):
        e=self.gateway.audit.append(kind,outcome,tuple((k,content_sha256(r)) for k,r in records),causes)
        return content_sha256(e)
    def _keep(self,state):self._current=content_sha256(state);return state
    def submit_text(self,text,*,source_id=None):
        self.gateway.invalidate();self._current=None
        try:result=assemble_text(text,self.provider,source_id=source_id or 'text:'+uuid4().hex)
        except StopRun:
            event=self.gateway.audit.append('INTERPRETATION_PRODUCED','HOSTED_BUDGET_OR_TRANSPORT_STOP',(('text',string_hash(text)),))
            return self._keep(LifecycleState(status='UPSTREAM_STOP',last_event_sha256=content_sha256(event),reason='HOSTED_BUDGET_OR_TRANSPORT_STOP'))
        raw=json_text(result);comp=(result.get('ponder') or {}).get('compilation')
        if result['status']!='OK' or comp is None:
            event=self.gateway.audit.append('INTERPRETATION_PRODUCED',result['status'],(('pipeline',string_hash(raw)),))
            return self._keep(LifecycleState(status='UPSTREAM_STOP',last_event_sha256=content_sha256(event),raw_pipeline_json=raw,reason=result.get('error') or (result.get('ponder') or {}).get('error') or result['status']))
        return self.submit_compilation(PonderCompilation.model_validate_json(json.dumps(comp)),raw_pipeline_json=raw)
    def submit_compilation(self,compilation,*,raw_pipeline_json=None):
        # This entry point is for explicit scripted compiler inputs and saved results.
        # It does not claim that a language model produced those inputs.
        self.gateway.invalidate();self._current=None
        c=PonderCompilation.model_validate(compilation);event=self._event('INTERPRETATION_PRODUCED',c.status,(('compilation',c),))
        view=consume(c)
        if view.status!='OK':return self._keep(LifecycleState(status='UPSTREAM_STOP',compilation=c,last_event_sha256=event,reason=view.status,raw_pipeline_json=raw_pipeline_json))
        g=ground(view,self.directory)
        event=self._event('GROUNDING','VERSION_BOUND',(('grounding',g),),(event,))
        return self._evaluate(c,g,(),event,raw_pipeline_json)
    def answer_grounding(self,state,choice_id,entity_id):
        if self._current!=content_sha256(state) or state.grounding is None or state.compilation is None:raise LifecycleError('STALE_CLARIFICATION')
        self.gateway.invalidate()
        successor=clarify(state.grounding,choice_id,entity_id,expected_state_sha256=content_sha256(state.grounding),expected_compilation_sha256=content_sha256(state.compilation))
        event=self._event('CLARIFICATION','EXPLICIT_ENTITY_CHOICE',(('before',state.grounding),('after',successor)),(state.last_event_sha256,))
        return self._evaluate(state.compilation,successor,(*state.grounding_parents,state.grounding),event,state.raw_pipeline_json)
    def _evaluate(self,c,g,parents,cause,raw):
        view=consume(c);data=build_input(view,g,grounding_parents=parents,directory=self.directory)
        decision=validate(data,self.provider);gate=assess_gate(data,decision)
        event=self._event('SEMANTIC_VALIDATION',gate.state,(('semantic_input',data),('decision',decision),('gate',gate)),(cause,))
        values=dict(compilation=c,grounding=g,grounding_parents=parents,semantic_input=data,semantic_input_sha256=content_sha256(data),semantic_decision=decision,semantic_gate=gate,last_event_sha256=event,raw_pipeline_json=raw)
        if gate.state!='ELIGIBLE_FOR_BUSINESS_CHECKS':
            status='NEEDS_GROUNDING' if g.clarifications else 'SEMANTIC_FROZEN'
            return self._keep(LifecycleState(status=status,**values))
        bi=build_business_input(data,decision,gate,self.gateway.bank,self.gateway.policy);br=validate_business(bi);bg=assess_business_gate(bi,br)
        event=self._event('BUSINESS_VALIDATION',bg.state,(('business_input',bi),('result',br),('gate',bg)),(event,))
        values.update(business_input=bi,business_result=br,business_gate=bg,last_event_sha256=event)
        if bg.state!='ELIGIBLE_FOR_CONFIRMATION':return self._keep(LifecycleState(status=bg.state,**values))
        try:review=prepare_review(bi,br,bg)
        except LifecycleError as error:return self._keep(LifecycleState(status='CONTRACT_ERROR',reason=str(error),**values))
        self.gateway.request_confirmation(review,cause=event)
        return self._keep(LifecycleState(status='READY_FOR_CONFIRMATION',review=review,**values))
