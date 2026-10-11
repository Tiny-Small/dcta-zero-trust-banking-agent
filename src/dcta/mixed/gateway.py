"""Shielded mock mixed gateway: exact registry authority, atomic in-process simulation."""
from typing import Literal
from dcta.ponder.base import FrozenRecord
from dcta.ponder.serialization import content_sha256
from dcta.lifecycle.records import Authorization,Transfer
from dcta.lifecycle.errors import LifecycleError
from dcta.shield.session import ShieldedGateway,review_data,reject_nested_bindings
from dcta.shield.scan import require_clean,ShieldViolation
from .business import InvestmentState,InvestmentPolicy,InvestmentPlan,InvestmentCompletion
from .review import MixedReview,verify_review

class SimulatedInvestment(FrozenRecord):
    schema_version: Literal['synthetic-investment-record-v1']='synthetic-investment-record-v1'
    id: str
    authorization_sha256: str
    plan: InvestmentPlan
    action: Literal['BUY','SELL']
    completion: InvestmentCompletion
    simulation: Literal[True]=True
    cash_settlement: Literal[False]=False

class MixedReceipt(FrozenRecord):
    schema_version: Literal['mixed-mock-receipt-v1']='mixed-mock-receipt-v1'
    authorization_sha256: str
    confirmation_sha256: str
    review_sha256: str
    idempotency_key: str
    transfers: tuple[Transfer,...]
    investment: SimulatedInvestment
    bank_before_sha256: str
    bank_after_sha256: str
    bank_after_revision: int
    investment_state_sha256: str
    investment_after_sha256: str
    investment_policy_sha256: str
    semantics: Literal['MOCK_ATOMIC_BANK_AND_SIMULATED_ORDER']='MOCK_ATOMIC_BANK_AND_SIMULATED_ORDER'

class MixedExecutionResult(FrozenRecord):
    status: Literal['SUCCEEDED','ALREADY_EXECUTED','FAILED']
    receipt: MixedReceipt | None=None
    code: str

class MixedGateway(ShieldedGateway):
    def __init__(self,bank,policy,investment_state,investment_policy,audit=None):
        require_clean(investment_state);require_clean(investment_policy)
        super().__init__(bank,policy,audit);self._investment_state=InvestmentState.model_validate(investment_state);self._investment_policy=InvestmentPolicy.model_validate(investment_policy);self._simulated_investments=()
    @property
    def investment_state(self):return self._investment_state
    @property
    def investment_policy(self):return self._investment_policy
    @property
    def simulated_investments(self):return self._simulated_investments
    def update_investment_context(self,state,policy):
        with self._lock:
            try:require_clean(state);require_clean(policy)
            except ShieldViolation:self.invalidate();raise
            state=InvestmentState.model_validate(state);policy=InvestmentPolicy.model_validate(policy)
            self._investment_state=state;self._investment_policy=policy;self.invalidate()
    def _context_live(self,review):
        if review.data.investment_state!=self._investment_state or review.data.investment_policy!=self._investment_policy:raise LifecycleError('STALE_INVESTMENT_CONTEXT')
    def _live(self,review):
        verify_review(review);self._context_live(review)
        if self._active!=content_sha256(review) or content_sha256(self.bank)!=review.data.bank_sha256 or content_sha256(self.policy)!=review.data.policy_sha256:raise LifecycleError('STALE_REVIEW')
    def request_confirmation(self,review,*,cause=None):
        with self._lock:
            try:
                require_clean(review_data(review));require_clean(review.data.investment_state);require_clean(review.data.investment_policy)
                reject_nested_bindings(review.data.semantic_input.snapshot,tuple(x.candidate for x in review.data.candidates))
                verify_review(review);self._context_live(review)
                if content_sha256(self.bank)!=review.data.bank_sha256 or content_sha256(self.policy)!=review.data.policy_sha256:raise LifecycleError('STALE_REVIEW')
            except ShieldViolation:
                self.invalidate();self.audit.append('CONFIRMATION_REJECTED','PROMPT_INJECTION_SHIELD_BLOCKED');raise
            rh=content_sha256(review);self._generation+=1;self._active=rh
            refs=[('review',rh),('payload',review.rendered_payload_sha256),('mixed_interpretation',content_sha256(review.data.semantic.interpretation))]
            refs.extend(('operation:'+x.candidate.id,content_sha256(x.candidate)) for x in review.data.candidates)
            refs.extend(('investment_action:'+a.candidate_id,content_sha256(a)) for a in review.data.semantic.interpretation.actions)
            e=self.audit.append('CONFIRMATION_REQUESTED','EXACT_MIXED_BUNDLE',tuple(refs),(cause,) if cause else ())
            self._requests[rh]=(review,content_sha256(e));return review
    # confirm/authorize are inherited unchanged: separate actor decisions,
    # exact request/review hash, registry equality and anti-revival generation.
    def _investment_record(self,review,authorization):
        ah=content_sha256(authorization)
        completion=InvestmentCompletion(id='simulated-investment:'+ah,user_id=self.bank.authenticated_user_id,day=self.bank.business_day,authorization_sha256=ah,plan_sha256=content_sha256(review.investment))
        return SimulatedInvestment(id=completion.id,authorization_sha256=ah,plan=review.investment,action=review.investment.action,completion=completion)
    def execute(self,authorization):
        with self._lock:
            ah=content_sha256(authorization) if type(authorization) is Authorization else None
            attempt=self.audit.append('EXECUTION_ATTEMPTED','MIXED_SUBMITTED',(('authorization',ah),) if ah else ())
            try:
                if type(authorization) is not Authorization or authorization.id not in self._authorizations or self._authorizations[authorization.id][0]!=authorization or authorization.status!='ACCEPTED':raise LifecycleError('EXACT_AUTHORIZATION_REQUIRED')
                a=authorization
                if self._active!=a.review_sha256 or a.generation!=self._generation or a.request_event_sha256!=self._requests[a.review_sha256][1]:raise LifecycleError('STALE_AUTHORIZATION')
                if a.id in self._executions:
                    receipt=self._executions[a.id];self.audit.append('EXECUTION_ALREADY_EXECUTED','NO_SECOND_DEBIT_OR_ORDER',(('receipt',content_sha256(receipt)),('authorization',ah)),(content_sha256(attempt),self._authorizations[a.id][1]))
                    return MixedExecutionResult(status='ALREADY_EXECUTED',receipt=receipt,code='NO_SECOND_DEBIT_OR_ORDER')
                review=self._requests[a.review_sha256][0];self._live(review);key=(a.actor_id,a.idempotency_key)
                if key in self._keys:raise LifecycleError('IDEMPOTENCY_KEY_CONFLICT')
                successor=self._successor(review,a) # accepted pure monetary planner
                investment=self._investment_record(review,a) # inert simulation
                next_state=InvestmentState.model_validate({**self.investment_state.model_dump(mode='python'),'revision':self.investment_state.revision+1,'completed_operations':(*self.investment_state.completed_operations,investment.completion)})
                receipt=MixedReceipt(authorization_sha256=ah,confirmation_sha256=a.confirmation_sha256,review_sha256=a.review_sha256,idempotency_key=a.idempotency_key,transfers=review.transfers,investment=investment,bank_before_sha256=content_sha256(self.bank),bank_after_sha256=content_sha256(successor),bank_after_revision=successor.revision,investment_state_sha256=content_sha256(self.investment_state),investment_after_sha256=content_sha256(next_state),investment_policy_sha256=content_sha256(self.investment_policy))
                investments=(*self._simulated_investments,investment);receipts=(*self._receipts,receipt)
                refs=[('receipt',content_sha256(receipt)),('bank_before',receipt.bank_before_sha256),('bank_after',receipt.bank_after_sha256),('authorization',ah),('investment_record',content_sha256(investment)),('investment_before',receipt.investment_state_sha256),('investment_after',receipt.investment_after_sha256)]
                refs.extend(('operation:'+x.candidate.id,content_sha256(x.candidate)) for x in review.data.candidates)
                self.audit.append('EXECUTION_SUCCEEDED','MOCK_ATOMIC_BANK_AND_SIMULATED_ORDER',tuple(refs),(content_sha256(attempt),self._authorizations[a.id][1]))
                self._bank=successor;self._investment_state=next_state;self._simulated_investments=investments;self._receipts=receipts;self._keys[key]=a.id;self._executions[a.id]=receipt
                return MixedExecutionResult(status='SUCCEEDED',receipt=receipt,code='MOCK_ATOMIC_BANK_AND_SIMULATED_ORDER')
            except LifecycleError as error:
                self.audit.append('EXECUTION_FAILED',str(error),(('authorization',ah),) if ah else (),(content_sha256(attempt),));raise
            except Exception:
                self.audit.append('EXECUTION_FAILED','MOCK_COMMIT_ABORTED',(('authorization',ah),) if ah else (),(content_sha256(attempt),))
                return MixedExecutionResult(status='FAILED',code='MOCK_COMMIT_ABORTED')
