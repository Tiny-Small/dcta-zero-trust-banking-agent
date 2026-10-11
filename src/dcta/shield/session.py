"""Separate shielded entry point. Accepted lifecycle contracts remain unchanged."""
import re
from dcta.ponder.input import EvidenceRef
from dcta.ponder.serialization import content_sha256
from dcta.validation.records import string_hash,json_text
from dcta.lifecycle.session import TextLifecycle,LifecycleState
from dcta.lifecycle.gateway import MockGateway
from .scan import require_clean,ShieldViolation
from .provider import ShieldedChoiceProvider


def review_data(review):
    return {'snapshot':review.data.semantic_input.snapshot.model_dump(mode='json'),
        'directory':review.data.semantic_input.directory.model_dump(mode='json') if review.data.semantic_input.directory else None,
        'grounding':review.data.semantic_input.grounding.model_dump(mode='json') if review.data.semantic_input.grounding else None,
        'bank':review.data.bank.model_dump(mode='json'),'policy':review.data.policy.model_dump(mode='json')}


def quoted_containers(source):
    # Structural containment only: never adds mentions, relations or intent.
    # Single apostrophes inside words are not quotation delimiters.
    patterns=(r'"[^"]*"',r"(?<!\w)'[^']*'(?!\w)",
        '“[^”]*”','‘[^’]*’','«[^»]*»','「[^」]*」','『[^』]*』')
    return tuple(EvidenceRef(source_id=source.id,start=m.start(),end=m.end(),text=m.group())
        for pattern in patterns for m in re.finditer(pattern,source.text))


def reject_nested_bindings(snapshot,candidates):
    if snapshot is None:return
    mentions={m.id:m for m in snapshot.semantic_mentions}
    scopes={p.mention_id:p for p in snapshot.ping_projection}
    containers=[m.evidence for m in snapshot.semantic_mentions if m.role=='payment_reference']
    containers.extend(a.evidence for a in snapshot.relational_anchors if a.kind=='NESTING')
    containers.extend(quoted_containers(snapshot.current_source))
    if snapshot.prior_context:
        mentions.update({m.id:m for m in snapshot.prior_context.semantic_mentions})
        scopes.update({p.mention_id:p for p in snapshot.prior_context.ping_projection})
        containers.extend(m.evidence for m in snapshot.prior_context.semantic_mentions if m.role=='payment_reference')
        containers.extend(a.evidence for a in snapshot.prior_context.relational_anchors if a.kind=='NESTING')
        for source in snapshot.prior_context.sources:containers.extend(quoted_containers(source))
    for candidate in candidates:
        for binding in candidate.bindings:
            if binding.field=='REFERENCE':continue
            for mid in binding.mention_ids:
                m=mentions.get(mid);p=scopes.get(mid)
                if p and p.producer_scope in {'NESTED_DATA','EXCLUDED_BY_SCOPE'}:raise ShieldViolation('SHIELD_NESTED_DATA_PROMOTION')
                if m and any(e.source_id==m.evidence.source_id and e.start<=m.evidence.start and m.evidence.end<=e.end for e in containers):raise ShieldViolation('SHIELD_QUOTED_FIELD_PROMOTION')


def reject_nested_current(compilation):
    reject_nested_bindings(compilation.input_snapshot,tuple(c for c in compilation.candidates if c.id in compilation.current_candidate_ids))

class ShieldedGateway(MockGateway):
    def __init__(self,bank,policy,audit=None):
        require_clean(bank);require_clean(policy);super().__init__(bank,policy,audit)
    def update_state(self,bank,policy):
        try:require_clean(bank);require_clean(policy)
        except ShieldViolation:
            self.invalidate();self.audit.append('BUSINESS_VALIDATION','PROMPT_INJECTION_SHIELD_BLOCKED');raise
        return super().update_state(bank,policy)
    def request_confirmation(self,review,*,cause=None):
        try:
            require_clean(review_data(review))
            reject_nested_bindings(review.data.semantic_input.snapshot,tuple(x.candidate for x in review.data.candidates))
        except ShieldViolation:
            self.invalidate();self.audit.append('CONFIRMATION_REJECTED','PROMPT_INJECTION_SHIELD_BLOCKED');raise
        return super().request_confirmation(review,cause=cause)
    def confirm(self,review,*,accepted,actor_id):
        try:require_clean(review_data(review));require_clean(actor_id)
        except ShieldViolation:
            self.invalidate();self.audit.append('CONFIRMATION_REJECTED','PROMPT_INJECTION_SHIELD_BLOCKED');raise
        return super().confirm(review,accepted=accepted,actor_id=actor_id)
    def authorize(self,confirmation,*,accepted,actor_id,idempotency_key):
        try:require_clean({'actor':actor_id,'idempotency_key':idempotency_key})
        except ShieldViolation:
            self.invalidate();self.audit.append('AUTHORIZATION_DENIED','PROMPT_INJECTION_SHIELD_BLOCKED');raise
        return super().authorize(confirmation,accepted=accepted,actor_id=actor_id,idempotency_key=idempotency_key)

class ShieldedTextLifecycle(TextLifecycle):
    def __init__(self,provider,gateway):
        if not isinstance(gateway,ShieldedGateway):raise ValueError('Shielded lifecycle requires shielded gateway')
        super().__init__(provider if isinstance(provider,ShieldedChoiceProvider) else ShieldedChoiceProvider(provider),gateway)
        self._text_submission=False
    def _block(self,error):
        self.gateway.invalidate();self._current=None
        payload={'version':'dcta-prompt-shield-v1','code':error.code,'findings':[f.model_dump(mode='json') for f in error.findings]}
        event=self.gateway.audit.append('INTERPRETATION_PRODUCED','PROMPT_INJECTION_SHIELD_BLOCKED',(('shield_observation',string_hash(json_text(payload))),))
        return self._keep(LifecycleState(status='UPSTREAM_STOP',reason='PROMPT_INJECTION_SHIELD_BLOCKED',last_event_sha256=content_sha256(event)))
    def _context(self):
        require_clean(self.directory);require_clean(self.gateway.bank);require_clean(self.gateway.policy)
    def submit_text(self,text,*,source_id=None):
        self.gateway.invalidate();self._current=None;self.provider.blocked=False
        self._text_submission=True
        try:
            require_clean({'transcript':text,'source_id':source_id});self._context()
            state=super().submit_text(text,source_id=source_id)
            return self._block(ShieldViolation('SHIELD_PROVIDER_QUARANTINE')) if self.provider.blocked else state
        except ShieldViolation as error:return self._block(error)
        finally:self._text_submission=False
    def submit_compilation(self,compilation,*,raw_pipeline_json=None):
        self.gateway.invalidate();self._current=None
        if not self._text_submission:self.provider.blocked=False
        try:
            if self.provider.blocked:raise ShieldViolation('SHIELD_PROVIDER_QUARANTINE')
            from dcta.ponder.ir import PonderCompilation
            try:compilation=PonderCompilation.model_validate(compilation)
            except (ValueError,TypeError):raise ShieldViolation('SHIELD_COMPILATION_CONTRACT')
            require_clean(compilation.input_snapshot);self._context();reject_nested_current(compilation)
            state=super().submit_compilation(compilation,raw_pipeline_json=raw_pipeline_json)
            return self._block(ShieldViolation('SHIELD_PROVIDER_QUARANTINE')) if self.provider.blocked else state
        except ShieldViolation as error:return self._block(error)
    def answer_grounding(self,state,choice_id,entity_id):
        try:
            require_clean({'choice_id':choice_id,'entity_id':entity_id});self._context()
            if state.compilation:require_clean(state.compilation.input_snapshot);reject_nested_current(state.compilation)
            require_clean(state.grounding);require_clean(state.grounding_parents)
            result=super().answer_grounding(state,choice_id,entity_id)
            return self._block(ShieldViolation('SHIELD_PROVIDER_QUARANTINE')) if self.provider.blocked else result
        except ShieldViolation as error:return self._block(error)
