"""Trusted in-process demo authority and locked atomic mock banking gateway.

Only registry-issued authorization artifacts enter execution. No real credentials,
biometrics, authorization service or external banking calls. Restart durability is
outside this MVP; all balances/history and idempotency records share one lifetime.
"""
from threading import RLock
from uuid import uuid4
from decimal import localcontext
from dcta.ponder.serialization import content_sha256
from dcta.business.records import MockBankState,MockBankPolicy,HistoryEntry,Balance
from dcta.business.input import decimal_record
from .records import Confirmation,Authorization,Receipt,ExecutionResult
from .review import verify_review
from .audit import AuditTrail
from .errors import LifecycleError


def replace(record,**updates):return type(record).model_validate({**record.model_dump(),**updates})

class MockGateway:
    def __init__(self,bank,policy,audit=None):
        self._bank=MockBankState.model_validate(bank);self._policy=MockBankPolicy.model_validate(policy)
        self.audit=audit if audit is not None else AuditTrail();self._lock=RLock();self._active=None;self._generation=0
        self._requests={};self._confirmations={};self._authorizations={};self._executions={};self._keys={};self._receipts=()
    @property
    def bank(self):return self._bank
    @property
    def policy(self):return self._policy
    @property
    def receipts(self):return self._receipts
    def invalidate(self):
        with self._lock:self._active=None;self._generation+=1
    def update_state(self,bank,policy):
        with self._lock:
            self._bank=MockBankState.model_validate(bank);self._policy=MockBankPolicy.model_validate(policy)
            self._active=None;self._generation+=1
    def _live(self,review):
        verify_review(review)
        if self._active!=content_sha256(review) or content_sha256(self._bank)!=review.data.bank_sha256 or content_sha256(self._policy)!=review.data.policy_sha256:raise LifecycleError('STALE_REVIEW')
    def request_confirmation(self,review,*,cause=None):
        with self._lock:
            verify_review(review)
            if content_sha256(self._bank)!=review.data.bank_sha256 or content_sha256(self._policy)!=review.data.policy_sha256:raise LifecycleError('STALE_REVIEW')
            rh=content_sha256(review);self._generation+=1;self._active=rh
            e=self.audit.append('CONFIRMATION_REQUESTED','EXACT_BUNDLE',(('review',rh),('payload',review.rendered_payload_sha256)),(cause,) if cause else ())
            self._requests[rh]=(review,content_sha256(e));return review
    def confirm(self,review,*,accepted,actor_id):
        with self._lock:
            try:
                self._live(review)
                if type(accepted) is not bool or actor_id!=self._bank.authenticated_user_id:raise LifecycleError('CONFIRMATION_ACTOR_OR_DECISION')
                rh=content_sha256(review)
                if rh not in self._requests or self._requests[rh][0]!=review:raise LifecycleError('CONFIRMATION_NOT_REQUESTED')
            except (LifecycleError,ValueError,TypeError,AttributeError):
                self.audit.append('CONFIRMATION_REJECTED','STALE_OR_INVALID');raise
            c=Confirmation(generation=self._generation,id='confirmation:'+uuid4().hex,status='ACCEPTED' if accepted else 'REJECTED',actor_id=actor_id,review_sha256=rh,rendered_payload_sha256=review.rendered_payload_sha256,request_event_sha256=self._requests[rh][1])
            e=self.audit.append('CONFIRMATION_ACCEPTED' if accepted else 'CONFIRMATION_REJECTED',c.status,(('confirmation',content_sha256(c)),('review',rh)),(c.request_event_sha256,))
            self._confirmations[c.id]=(c,content_sha256(e));return c
    def authorize(self,confirmation,*,accepted,actor_id,idempotency_key):
        with self._lock:
            try:
                if type(confirmation) is not Confirmation or confirmation.id not in self._confirmations or self._confirmations[confirmation.id][0]!=confirmation or confirmation.status!='ACCEPTED':raise LifecycleError('CONFIRMATION_NOT_ACCEPTED')
                review=self._requests[confirmation.review_sha256][0];self._live(review)
                if confirmation.generation!=self._generation or confirmation.request_event_sha256!=self._requests[confirmation.review_sha256][1]:raise LifecycleError('STALE_CONFIRMATION_GENERATION')
                if type(accepted) is not bool or actor_id!=confirmation.actor_id or actor_id!=self._bank.authenticated_user_id or not isinstance(idempotency_key,str) or not 1<=len(idempotency_key)<=120:raise LifecycleError('AUTHORIZATION_ACTOR_OR_KEY')
            except (LifecycleError,ValueError,TypeError,AttributeError):
                self.audit.append('AUTHORIZATION_DENIED','STALE_OR_INVALID');raise
            a=Authorization(generation=confirmation.generation,request_event_sha256=confirmation.request_event_sha256,id='authorization:'+uuid4().hex,status='ACCEPTED' if accepted else 'DENIED',actor_id=actor_id,review_sha256=confirmation.review_sha256,confirmation_sha256=content_sha256(confirmation),confirmation_event_sha256=self._confirmations[confirmation.id][1],idempotency_key=idempotency_key)
            e=self.audit.append('AUTHORIZATION_ACCEPTED' if accepted else 'AUTHORIZATION_DENIED',a.status,(('authorization',content_sha256(a)),('confirmation',a.confirmation_sha256),('review',a.review_sha256)),(a.confirmation_event_sha256,))
            self._authorizations[a.id]=(a,content_sha256(e));return a
    def _successor(self,review,authorization):
        accounts={a.entity_id:a for a in self._bank.accounts};history=list(self._bank.history)
        with localcontext() as context:
            context.prec=200
            for n,t in enumerate(review.transfers):
                account=accounts[t.source_account_id];amount=decimal_record(t.amount)
                balances=[];found=False
                for b in account.balances:
                    if b.currency==t.currency:
                        remaining=decimal_record(b.available)-amount
                        if remaining<0:raise LifecycleError('EXECUTION_FUNDS_CHANGED')
                        balances.append(Balance(currency=b.currency,available=str(remaining)));found=True
                    else:balances.append(b)
                if not found:raise LifecycleError('EXECUTION_CURRENCY_CHANGED')
                accounts[account.entity_id]=replace(account,balances=tuple(balances))
                if t.target_kind=='ACCOUNT':
                    dest=accounts[t.target_entity_id];db=[];credited=False
                    for b in dest.balances:
                        if b.currency==t.currency:db.append(Balance(currency=b.currency,available=str(decimal_record(b.available)+amount)));credited=True
                        else:db.append(b)
                    if not credited:db.append(Balance(currency=t.currency,available=str(amount)))
                    accounts[dest.entity_id]=replace(dest,balances=tuple(db))
                history.append(HistoryEntry(id=authorization.id+':'+str(n),user_id=self._bank.authenticated_user_id,day=self._bank.business_day,source_account_id=t.source_account_id,currency=t.currency,amount=t.amount,source_id=self._policy.trusted_history_source,source_version=self._policy.trusted_history_version))
        return replace(self._bank,revision=self._bank.revision+1,snapshot_id='mock:executed:'+authorization.id,accounts=tuple(accounts[a.entity_id] for a in self._bank.accounts),history=tuple(history))
    def execute(self,authorization):
        with self._lock:
            ah=content_sha256(authorization) if type(authorization) is Authorization else None
            attempt=self.audit.append('EXECUTION_ATTEMPTED','SUBMITTED',(('authorization',ah),) if ah else ())
            try:
                if type(authorization) is not Authorization or authorization.id not in self._authorizations or self._authorizations[authorization.id][0]!=authorization or authorization.status!='ACCEPTED':raise LifecycleError('EXACT_AUTHORIZATION_REQUIRED')
                a=authorization
                if self._active!=a.review_sha256 or a.generation!=self._generation or a.request_event_sha256!=self._requests[a.review_sha256][1]:raise LifecycleError('STALE_AUTHORIZATION')
                if a.id in self._executions:
                    receipt=self._executions[a.id]
                    self.audit.append('EXECUTION_ALREADY_EXECUTED','NO_SECOND_DEBIT',(('receipt',content_sha256(receipt)),('authorization',ah)),(content_sha256(attempt),self._authorizations[a.id][1]))
                    return ExecutionResult(status='ALREADY_EXECUTED',receipt=receipt,code='NO_SECOND_DEBIT')
                review=self._requests[a.review_sha256][0];self._live(review)
                key=(a.actor_id,a.idempotency_key)
                if key in self._keys:raise LifecycleError('IDEMPOTENCY_KEY_CONFLICT')
                successor=self._successor(review,a)
                receipt=Receipt(authorization_sha256=ah,confirmation_sha256=a.confirmation_sha256,review_sha256=a.review_sha256,idempotency_key=a.idempotency_key,transfers=review.transfers,bank_before_sha256=content_sha256(self._bank),bank_after_sha256=content_sha256(successor),bank_after_revision=successor.revision)
                # Audit append is checked before the single state/journal commit.
                self.audit.append('EXECUTION_SUCCEEDED','ATOMIC_BUNDLE',(('receipt',content_sha256(receipt)),('bank_before',receipt.bank_before_sha256),('bank_after',receipt.bank_after_sha256),('authorization',ah)),(content_sha256(attempt),self._authorizations[a.id][1]))
                self._bank=successor;self._keys[key]=a.id;self._executions[a.id]=receipt;self._receipts=(*self._receipts,receipt)
                return ExecutionResult(status='SUCCEEDED',receipt=receipt,code='ATOMIC_BUNDLE')
            except LifecycleError as error:
                self.audit.append('EXECUTION_FAILED',str(error),(('authorization',ah),) if ah else (),(content_sha256(attempt),))
                raise
            except Exception:
                # A synthetic adapter/planning fault aborts before state publication.
                # Never put exception text (which could contain secrets) into audit.
                self.audit.append('EXECUTION_FAILED','MOCK_COMMIT_ABORTED',(('authorization',ah),) if ah else (),(content_sha256(attempt),))
                return ExecutionResult(status='FAILED',code='MOCK_COMMIT_ABORTED')
