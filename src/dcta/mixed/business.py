"""Deterministic versioned mixed admission, unchanged monetary rules, no prices."""
import re
from typing import Literal
from dcta.ponder.base import FrozenRecord
from dcta.ponder.serialization import content_sha256
from dcta.ponder_mvp.consumer import consume
from dcta.business.records import (MockBankState,MockBankPolicy,OperationBusinessResult,BusinessFinding,FundsLedgerEntry)
from dcta.business.input import (BusinessValidationInput,build_business_input as old_input,integrity_errors as old_integrity,decimal_record)
from dcta.business.checks import check_operation,aggregate_funds,velocity_findings,combine,finding
from dcta.validation.records import json_text,string_hash
from dcta.validation.engine import validate as old_validate
from dcta.validation.gate import assess_gate as old_gate
from .validation import MixedSemanticInput,MixedSemanticDecision,MixedSemanticGate,assess_gate
from .records import InvestmentAction

class InvestmentCompletion(FrozenRecord):
    id: str
    user_id: str
    day: str
    authorization_sha256: str
    plan_sha256: str
    source: Literal['mixed-mock-gateway-v1']='mixed-mock-gateway-v1'

class InvestmentState(FrozenRecord):
    version: str='synthetic-investment-state-v2'
    revision: int=0
    completed_operations: tuple[InvestmentCompletion,...]=()
    account_id: str='synthetic:investment-demo'
    owner_id: str='mock:user:demo'
    eligible: bool=True

class InvestmentPolicy(FrozenRecord):
    version: str='synthetic-investment-policy-v2'
    count_semantics: Literal['COMPLETED_BANK_AND_SIMULATED_OPERATIONS_PER_USER_DAY']='COMPLETED_BANK_AND_SIMULATED_OPERATIONS_PER_USER_DAY'
    supported_asset_ids: tuple[str,...]=('asset:dbs',)
    permitted_actions: tuple[Literal['BUY','SELL'],...]=('BUY','SELL')
    maximum_quantity: str='100'
    semantics: Literal['SIMULATED_ORDER_NO_PRICE_NO_CASH_SETTLEMENT']='SIMULATED_ORDER_NO_PRICE_NO_CASH_SETTLEMENT'

class InvestmentPlan(FrozenRecord):
    candidate_id: str
    version_id: str
    candidate_sha256: str
    action: Literal['BUY','SELL']
    action_record: InvestmentAction
    asset_entity_id: str
    asset_label: str
    quantity: str
    evidence_ids: tuple[str,...]
    simulation: Literal[True]=True
    cash_settlement: Literal[False]=False

class MixedBusinessInput(FrozenRecord):
    schema_version: Literal['mixed-business-input-v1']='mixed-business-input-v1'
    semantic: MixedSemanticInput
    decision: MixedSemanticDecision
    gate: MixedSemanticGate
    legacy_transport: BusinessValidationInput
    investment_state: InvestmentState
    investment_policy: InvestmentPolicy
    @property
    def semantic_input(self):return self.semantic.core
    @property
    def semantic_decision_sha256(self):return content_sha256(self.decision)
    @property
    def candidates(self):return self.legacy_transport.candidates
    @property
    def targets(self):return self.legacy_transport.targets
    @property
    def bank(self):return self.legacy_transport.bank
    @property
    def bank_sha256(self):return self.legacy_transport.bank_sha256
    @property
    def policy(self):return self.legacy_transport.policy
    @property
    def policy_sha256(self):return self.legacy_transport.policy_sha256
    @property
    def grounded_fields(self):return self.legacy_transport.grounded_fields
    @property
    def conditions(self):return self.legacy_transport.conditions
    @property
    def bundle_sha256(self):return string_hash(json_text({'interpretation':content_sha256(self.semantic.interpretation),'semantic_input':content_sha256(self.semantic),'targets':[t.model_dump(mode='json') for t in self.targets]}))

class MixedBusinessResult(FrozenRecord):
    schema_version: Literal['mixed-business-result-v1']='mixed-business-result-v1'
    status: Literal['PASS','NEEDS_CLARIFICATION','BLOCKED','CONTRACT_ERROR']
    input_sha256: str
    bundle_sha256: str
    operations: tuple[OperationBusinessResult,...]
    findings: tuple[BusinessFinding,...]
    funds_ledger: tuple[FundsLedgerEntry,...]
    investment: InvestmentPlan | None=None
    confirmed: Literal[False]=False
    authorized: Literal[False]=False
    executable: Literal[False]=False


def mock_investment_state():return InvestmentState()
def mock_investment_policy():return InvestmentPolicy()


def _legacy(semantic,bank,policy):
    # Retain and validate legacy bank transport without granting old semantic
    # eligibility: its original investment decision remains UNRESOLVED.
    si=semantic.core;decision=old_validate(si);return old_input(si,decision,old_gate(si,decision),bank,policy)


def build_business_input(semantic,decision,gate,bank,policy,investment_state,investment_policy):
    semantic=MixedSemanticInput.model_validate(semantic)
    return MixedBusinessInput(semantic=semantic,decision=decision,gate=gate,legacy_transport=_legacy(semantic,bank,policy),investment_state=investment_state,investment_policy=investment_policy)


def integrity_errors(data):
    out=[]
    gate=assess_gate(data.semantic,data.decision)
    if data.gate!=gate or gate.state!='ELIGIBLE_FOR_BUSINESS_CHECKS':out.append('exact mixed semantic MATCH admission required')
    if _legacy(data.semantic,data.bank,data.policy)!=data.legacy_transport:out.append('legacy bank transport replay')
    out.extend(e for e in old_integrity(data.legacy_transport) if e!='semantic admission: exact MATCH gate required')
    # The removed old admission finding is replaced, not waived, by the exact
    # new gate above. All bank/policy/history/condition integrity rules retained.
    if len(data.candidates)!=2 or sorted(c.candidate.goal for c in data.candidates) not in (['investment','transfer'],['investment','payment']):out.append('mixed bundle requires both complete current legs')
    p=data.investment_policy;s=data.investment_state
    cap=decimal_record(p.maximum_quantity)
    if not p.version or len(set(p.supported_asset_ids))!=len(p.supported_asset_ids) or not p.supported_asset_ids or len(set(p.permitted_actions))!=len(p.permitted_actions) or not p.permitted_actions or cap is None or cap<=0:out.append('synthetic investment policy integrity')
    if not s.version or not s.account_id or not s.owner_id or s.revision<0:out.append('synthetic investment state identity')
    if len({h.id for h in s.completed_operations})!=len(s.completed_operations):out.append('duplicate synthetic completed operation')
    for h in s.completed_operations:
        if not h.user_id or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',h.day) or not re.fullmatch(r'[0-9a-f]{64}',h.authorization_sha256) or not re.fullmatch(r'[0-9a-f]{64}',h.plan_sha256) or h.id!='simulated-investment:'+h.authorization_sha256:out.append('synthetic completed operation integrity')
    return tuple(sorted(set(out)))


def _investment(data,item,target):
    c=item.candidate;ms={m.id:m for m in item.mentions};bindings={b.field:b for b in c.bindings};out=[];plan=None
    def add(status,code,field,value,message):out.append(finding(data,status,code,field,value,message,item=item,records=(data.investment_state,data.investment_policy),record_ids=(data.investment_state.account_id,data.investment_policy.version)))
    action=next((a for a in data.semantic.interpretation.actions if a.candidate_id==c.id),None)
    if action is None or action.action not in data.investment_policy.permitted_actions:add('NEEDS_CLARIFICATION','INVESTMENT_ACTION_REQUIRED','INVESTMENT_ACTION','UNSPECIFIED','No default BUY; explicitly supported permitted action required')
    else:add('PASS','INVESTMENT_ACTION_SUPPORTED','INVESTMENT_ACTION',action.action,'Explicit version-bound source predicate action')
    asset=next((f for f in data.grounded_fields if f.candidate_id==c.id and f.field=='ASSET'),None)
    if asset is None or asset.status!='RESOLVED' or asset.selected_entity_id not in data.investment_policy.supported_asset_ids:add('BLOCKED','INVESTMENT_ASSET_UNSUPPORTED','ASSET',asset.literal if asset else '', 'Exactly resolved supported synthetic product required')
    else:add('PASS','INVESTMENT_ASSET_SUPPORTED','ASSET',asset.selected_entity_id,'Supported synthetic product; no market lookup')
    q=bindings['QUANTITY'];m=ms.get(q.mention_ids[0]) if len(q.mention_ids)==1 and q.status=='BOUND' else None
    quantity=decimal_record(m.evidence.text.strip()) if m else None
    if quantity is None or quantity<=0 or quantity!=quantity.to_integral_value() or quantity>decimal_record(data.investment_policy.maximum_quantity):add('BLOCKED','INVESTMENT_QUANTITY_INVALID','QUANTITY',m.evidence.text if m else '', 'Positive whole shares within explicit synthetic cap; no money conversion')
    else:add('PASS','INVESTMENT_QUANTITY_SUPPORTED','QUANTITY',quantity,'Exact whole source-backed shares; no price or consideration invented')
    eligible=data.investment_state.eligible and data.investment_state.owner_id==data.bank.authenticated_user_id
    add('PASS' if eligible else 'BLOCKED','INVESTMENT_PRODUCT_ELIGIBILITY','ASSET',eligible,'Trusted synthetic account/product eligibility; no suitability model')
    if any(b.mention_ids for b in c.bindings if b.field not in {'ASSET','QUANTITY'}):add('BLOCKED','INVESTMENT_FUNDING_UNMODELED','AMOUNT','','Synthetic investment supports no cash consideration or silently shared source')
    status=combine(f.result for f in out)
    if status=='PASS':
        entity=next(e for e in asset.matches if e.id==asset.selected_entity_id)
        plan=InvestmentPlan(candidate_id=c.id,version_id=c.version_id,candidate_sha256=content_sha256(c),action=action.action,action_record=action,asset_entity_id=entity.id,asset_label=entity.name,quantity=str(quantity),evidence_ids=('mention:'+m.id,'mention:'+asset.mention_id,'anchor:'+action.anchor_id))
    return OperationBusinessResult(target=target,status=status,findings=tuple(out)),plan


def validate_business(data):
    data=MixedBusinessInput.model_validate(data);errors=integrity_errors(data);ops=[];fundings=[];plan=None;ledger=();findings=[]
    if errors:
        findings=[finding(data,'CONTRACT_ERROR','MIXED_BUSINESS_INTEGRITY','INPUT',e,'Mixed semantic admission or deterministic state integrity failed') for e in errors]
    else:
        for item,target in zip(data.candidates,data.targets):
            if item.candidate.goal=='investment':op,plan=_investment(data,item,target);funding=None
            else:op,funding=check_operation(data,item,target)
            ops.append(op);fundings.append(funding)
        ops,ledger=aggregate_funds(data,ops,fundings)
        # Preserve frozen monetary velocity rules. Replace only their count
        # finding with the explicit mixed-domain completed-operation contract.
        findings=[f for f in velocity_findings(data,fundings) if f.code not in {'DAILY_COUNT_CHECKED','DAILY_COUNT_LIMIT'}]
        history=tuple(h for h in data.bank.history if h.day==data.bank.business_day and h.user_id==data.bank.authenticated_user_id)
        simulated=tuple(h for h in data.investment_state.completed_operations if h.day==data.bank.business_day and h.user_id==data.bank.authenticated_user_id)
        count=len(history)+len(simulated)+len(data.candidates);ok=count<=data.policy.daily_transaction_count_limit
        findings.append(finding(data,'PASS' if ok else 'BLOCKED','MIXED_DAILY_COUNT_CHECKED' if ok else 'MIXED_DAILY_COUNT_LIMIT','BUNDLE',count,'Trusted completed banking and simulated operations for this user/day plus every proposed operation',records=(*history,*simulated,data.policy,data.investment_policy),record_ids=(data.bank.business_day,data.investment_policy.version)))
    return MixedBusinessResult(status=combine([*(o.status for o in ops),*(f.result for f in findings)]),input_sha256=content_sha256(data),bundle_sha256=data.bundle_sha256,operations=tuple(ops),findings=tuple(findings),funds_ledger=tuple(ledger),investment=plan)
