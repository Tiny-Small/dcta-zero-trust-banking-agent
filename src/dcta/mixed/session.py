"""Explicitly shielded mixed API, no changes to accepted text lifecycle."""
from typing import Literal
from dcta.ponder.base import FrozenRecord
from dcta.ponder.serialization import content_sha256
from dcta.validation.records import json_text,string_hash
from dcta.shield.session import ShieldedTextLifecycle,reject_nested_current
from dcta.shield.scan import require_clean,ShieldViolation
from dcta.ponder_mvp.bridge import extract_text,snapshot_from_extraction
from dcta.ponder_mvp.consumer import consume
from dcta.ponder_mvp.grounding import GroundingState,ground,clarify
from dcta.ponder_mvp.demo import StopRun
from dcta.lifecycle.errors import LifecycleError
from .provider import MixedChoiceProvider
from .records import MixedInterpretation
from .policy import assemble_snapshot,build_registry,verify_interpretation
from .validation import (MixedSemanticInput,MixedSemanticDecision,MixedSemanticGate,build_input,validate_mixed,assess_gate)
from .business import (MixedBusinessInput,MixedBusinessResult,build_business_input,validate_business)
from .review import MixedReview,prepare_review,assess_business_gate
from .gateway import MixedGateway

class MixedLifecycleState(FrozenRecord):
    schema_version: Literal['mixed-lifecycle-state-v1']='mixed-lifecycle-state-v1'
    status: Literal['UPSTREAM_STOP','UNSUPPORTED','LIMIT_EXCEEDED','NEEDS_GROUNDING','SEMANTIC_FROZEN','NEEDS_CLARIFICATION','BLOCKED','CONTRACT_ERROR','READY_FOR_CONFIRMATION']
    interpretation: MixedInterpretation | None=None
    grounding: GroundingState | None=None
    grounding_parents: tuple[GroundingState,...]=()
    semantic_input: MixedSemanticInput | None=None
    semantic_decision: MixedSemanticDecision | None=None
    semantic_gate: MixedSemanticGate | None=None
    business_input: MixedBusinessInput | None=None
    business_result: MixedBusinessResult | None=None
    review: MixedReview | None=None
    last_event_sha256: str
    raw_pipeline_json: str | None=None
    counts: tuple[tuple[str,int],...]=()
    reason: str=''
    @property
    def compilation(self):return self.interpretation.compilation if self.interpretation else None

class MixedTextLifecycle(ShieldedTextLifecycle):
    def __init__(self,provider,gateway):
        if not isinstance(gateway,MixedGateway):raise ValueError('Mixed shielded gateway required')
        super().__init__(provider if isinstance(provider,MixedChoiceProvider) else MixedChoiceProvider(provider),gateway)
    def _context(self):
        super()._context();require_clean(self.gateway.investment_state);require_clean(self.gateway.investment_policy)
    def _block(self,error):
        stopped=super()._block(error)
        return self._keep(MixedLifecycleState(status=stopped.status,reason=stopped.reason,last_event_sha256=stopped.last_event_sha256))
    def _stop(self,status,reason,*,records=(),raw=None,counts=()):
        event=self.gateway.audit.append('INTERPRETATION_PRODUCED',status,tuple((k,content_sha256(r)) for k,r in records))
        return self._keep(MixedLifecycleState(status=status,reason=reason,last_event_sha256=content_sha256(event),raw_pipeline_json=raw,counts=counts))
    def submit_compilation(self,compilation,*,raw_pipeline_json=None):
        self.gateway.invalidate();self._current=None
        return self._stop('UNSUPPORTED','Mixed API requires versioned interpretation with explicit action decisions; never synthesize BUY from compiler goal')
    def submit_text(self,text,*,source_id=None):
        self.gateway.invalidate();self._current=None;self.provider.blocked=False;self._text_submission=True
        try:
            require_clean({'transcript':text,'source_id':source_id});self._context()
            stages=extract_text(text,self.provider,source_id=source_id or 'mixed:input')
            snapshot=snapshot_from_extraction(stages);require_clean(snapshot);registry=build_registry(snapshot)
            counts=(('extractor_candidates',len(stages['raw'].get('candidates',[]))),*registry.counts)
            raw=json_text({'extraction':stages,'registry':registry.model_dump(mode='json')})
            if self.provider.blocked:raise ShieldViolation('SHIELD_PROVIDER_QUARANTINE')
            if registry.status!='READY':return self._stop(registry.status,registry.reason,records=(('snapshot',snapshot),('registry',registry)),raw=raw,counts=counts)
            i=assemble_snapshot(snapshot,self.provider)
            return self.submit_interpretation(i,raw_pipeline_json=raw,counts=counts)
        except ShieldViolation as error:return self._block(error)
        except StopRun:return self._stop('UPSTREAM_STOP','HOSTED_BUDGET_OR_TRANSPORT_STOP')
        except (ValueError,TypeError) as error:
            if self.provider.blocked:return self._block(ShieldViolation('SHIELD_PROVIDER_QUARANTINE'))
            return self._stop('UNSUPPORTED' if str(error).startswith('UNSUPPORTED') else 'CONTRACT_ERROR','MIXED_UPSTREAM_CONTRACT_STOP')
        finally:self._text_submission=False
    def submit_interpretation(self,interpretation,*,raw_pipeline_json=None,counts=()):
        self.gateway.invalidate();self._current=None
        if not self._text_submission:self.provider.blocked=False
        try:
            if self.provider.blocked:raise ShieldViolation('SHIELD_PROVIDER_QUARANTINE')
            i=verify_interpretation(interpretation);require_clean(i.compilation.input_snapshot);self._context();reject_nested_current(i.compilation)
            c=i.compilation;event=self._event('INTERPRETATION_PRODUCED',c.status,(('mixed_interpretation',i),('compilation',c),('mixed_relations',i.relations)))
            for candidate in c.candidates:
                event=self._event('INTERPRETATION_PRODUCED','OPERATION_EVIDENCE',( ('operation:'+candidate.id,candidate),),(event,))
            for action in i.actions:event=self._event('INTERPRETATION_PRODUCED','INVESTMENT_ACTION',( ('investment_action:'+action.candidate_id,action),),(event,))
            view=consume(c)
            if view.status!='OK':return self._keep(MixedLifecycleState(status='CONTRACT_ERROR',interpretation=i,last_event_sha256=event,reason=view.status,counts=counts,raw_pipeline_json=raw_pipeline_json))
            g=ground(view,self.directory);event=self._event('GROUNDING','VERSION_BOUND',(('grounding',g),),(event,))
            return self._evaluate_mixed(i,g,(),event,raw_pipeline_json,counts)
        except ShieldViolation as error:return self._block(error)
        except StopRun:return self._stop('UPSTREAM_STOP','HOSTED_BUDGET_OR_TRANSPORT_STOP')
        except (ValueError,TypeError):return self._stop('CONTRACT_ERROR','MIXED_INPUT_CONTRACT_STOP')
    def _evaluate_mixed(self,i,g,parents,cause,raw,counts):
        data=build_input(i,g,parents,self.directory);decision=validate_mixed(data,self.provider)
        if self.provider.blocked:raise ShieldViolation('SHIELD_PROVIDER_QUARANTINE')
        gate=assess_gate(data,decision)
        event=self._event('SEMANTIC_VALIDATION',gate.state,(('mixed_semantic_input',data),('decision',decision),('gate',gate)),(cause,))
        values=dict(interpretation=i,grounding=g,grounding_parents=parents,semantic_input=data,semantic_decision=decision,semantic_gate=gate,last_event_sha256=event,counts=counts,raw_pipeline_json=raw)
        if gate.state!='ELIGIBLE_FOR_BUSINESS_CHECKS':return self._keep(MixedLifecycleState(status='NEEDS_GROUNDING' if g.clarifications else 'SEMANTIC_FROZEN',**values))
        bi=build_business_input(data,decision,gate,self.gateway.bank,self.gateway.policy,self.gateway.investment_state,self.gateway.investment_policy)
        result=validate_business(bi);business_gate=assess_business_gate(bi,result)
        event=self._event('BUSINESS_VALIDATION',business_gate.state,(('business_input',bi),('business_result',result),('business_gate',business_gate)),(event,));values.update(business_input=bi,business_result=result,last_event_sha256=event)
        if business_gate.state!='ELIGIBLE_FOR_CONFIRMATION':return self._keep(MixedLifecycleState(status=business_gate.state,**values))
        review=prepare_review(bi,result);self.gateway.request_confirmation(review,cause=event)
        return self._keep(MixedLifecycleState(status='READY_FOR_CONFIRMATION',review=review,**values))
    def answer_grounding(self,state,choice_id,entity_id):
        try:
            require_clean({'choice_id':choice_id,'entity_id':entity_id});self._context()
            if self._current!=content_sha256(state) or state.grounding is None or state.interpretation is None:raise LifecycleError('STALE_CLARIFICATION')
            require_clean(state.compilation.input_snapshot);reject_nested_current(state.compilation);require_clean(state.grounding);require_clean(state.grounding_parents)
            self.gateway.invalidate()
            successor=clarify(state.grounding,choice_id,entity_id,expected_state_sha256=content_sha256(state.grounding),expected_compilation_sha256=state.grounding.compilation_sha256)
            event=self._event('CLARIFICATION','EXPLICIT_ENTITY_CHOICE',(('before',state.grounding),('after',successor)),(state.last_event_sha256,))
            return self._evaluate_mixed(state.interpretation,successor,(*state.grounding_parents,state.grounding),event,state.raw_pipeline_json,state.counts)
        except ShieldViolation as error:return self._block(error)
        except StopRun:return self._stop('UPSTREAM_STOP','HOSTED_BUDGET_OR_TRANSPORT_STOP')
