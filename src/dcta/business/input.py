"""Closed business transport + exact semantic admission; no intent inference."""
import re
from datetime import date
from decimal import Decimal,InvalidOperation
from typing import Literal
from dcta.ponder.base import FrozenRecord
from dcta.ponder.serialization import content_sha256
from dcta.ponder_mvp.consumer import CurrentCandidate
from dcta.ponder_mvp.grounding import GroundedField
from dcta.validation.input import ValidationInput
from dcta.validation.records import ValidationDecision,ValidationTarget
from dcta.validation.gate import FreezeGate,assess_gate
from .records import MockBankState,MockBankPolicy,BusinessCondition,BusinessBundle

class BusinessValidationInput(FrozenRecord):
    schema_version: Literal['business-validation-input-v1']='business-validation-input-v1'
    semantic_input: ValidationInput
    semantic_decision: ValidationDecision
    semantic_gate: FreezeGate
    semantic_input_sha256: str
    semantic_decision_sha256: str
    semantic_gate_sha256: str
    candidates: tuple[CurrentCandidate,...]
    targets: tuple[ValidationTarget,...]
    bundle_sha256: str
    compilation_sha256: str
    grounding_sha256: str | None
    grounding_revision: int | None
    grounded_fields: tuple[GroundedField,...]
    conditions: tuple[BusinessCondition,...]
    bank: MockBankState
    bank_sha256: str
    policy: MockBankPolicy
    policy_sha256: str


def _targets(si):
    return tuple(ValidationTarget(candidate_id=x.candidate.id,frame_id=x.candidate.frame_id,version_id=x.candidate.version_id,candidate_sha256=content_sha256(x.candidate)) for x in si.targets)


def _conditions(si):
    anchors={a.id:a for a in si.snapshot.relational_anchors}
    if si.snapshot.prior_context:anchors.update({a.id:a for a in si.snapshot.prior_context.relational_anchors})
    return tuple(BusinessCondition(candidate_id=x.candidate.id,version_id=x.candidate.version_id,candidate_sha256=content_sha256(x.candidate),anchor_id=aid,anchor_sha256=content_sha256(anchors[aid]),evidence=anchors[aid].evidence)
        for x in si.targets for aid in x.projection.condition_anchor_ids if aid in anchors)


def _bundle(si):return BusinessBundle(compilation_sha256=si.compilation_sha256,targets=_targets(si),grounding_sha256=si.grounding_sha256,semantic_input_sha256=content_sha256(si))


def build_business_input(semantic_input,semantic_decision,semantic_gate,bank,policy):
    si=ValidationInput.model_validate(semantic_input);sd=ValidationDecision.model_validate(semantic_decision);sg=FreezeGate.model_validate(semantic_gate)
    bank=MockBankState.model_validate(bank);policy=MockBankPolicy.model_validate(policy)
    return BusinessValidationInput(semantic_input=si,semantic_decision=sd,semantic_gate=sg,semantic_input_sha256=content_sha256(si),semantic_decision_sha256=content_sha256(sd),semantic_gate_sha256=content_sha256(sg),
        candidates=si.targets,targets=_targets(si),bundle_sha256=content_sha256(_bundle(si)),compilation_sha256=si.compilation_sha256,grounding_sha256=si.grounding_sha256,grounding_revision=si.grounding_revision,
        grounded_fields=si.grounding.fields if si.grounding else (),conditions=_conditions(si),bank=bank,bank_sha256=content_sha256(bank),policy=policy,policy_sha256=content_sha256(policy))


def decimal_record(value):
    if not isinstance(value,str) or len(value)>80 or not re.fullmatch(r'[+-]?\d+(?:\.\d+)?',value):return None
    try:
        d=Decimal(value)
        return d if d.is_finite() else None
    except InvalidOperation:return None


def integrity_errors(data):
    data=BusinessValidationInput.model_validate(data);out=[];si=data.semantic_input
    for key,record in [('semantic_input',si),('semantic_decision',data.semantic_decision),('semantic_gate',data.semantic_gate),('bank',data.bank),('policy',data.policy)]:
        if content_sha256(record)!=getattr(data,key+'_sha256'):out.append({'bank':'bank state hash','policy':'policy hash'}.get(key,key+' hash'))
    gate=assess_gate(si,data.semantic_decision)
    if gate!=data.semantic_gate or gate.result!='MATCH' or gate.state!='ELIGIBLE_FOR_BUSINESS_CHECKS':out.append('semantic admission: exact MATCH gate required')
    if si.focus_candidate_id is not None or si.targets!=si.context:out.append('semantic admission: complete current bundle required')
    if data.candidates!=si.targets or data.targets!=_targets(si) or data.semantic_decision.targets!=data.targets:out.append('candidate/target membership')
    if data.bundle_sha256!=content_sha256(_bundle(si)) or data.compilation_sha256!=si.compilation_sha256:out.append('bundle/compilation hash')
    if data.grounding_sha256!=si.grounding_sha256 or data.grounding_revision!=si.grounding_revision or data.grounded_fields!=(si.grounding.fields if si.grounding else ()):out.append('grounding revision/content')
    if data.conditions!=_conditions(si):out.append('condition transport')
    mapping_keys={(f.candidate_id,f.field,f.mention_id) for f in data.grounded_fields}
    if len(mapping_keys)!=len(data.grounded_fields):out.append('duplicate grounded field mapping')
    b=data.bank;p=data.policy
    if not b.version or b.revision<0 or not b.snapshot_id or not b.authenticated_user_id:out.append('bank observation identity')
    if b.directory_sha256!=si.directory_sha256 or si.directory is None:out.append('bank/grounding directory provenance')
    if not p.version or not p.currencies or len(set(p.supported_goals))!=len(p.supported_goals):out.append('policy identity/goals')
    if len({c.iso for c in p.currencies})!=len(p.currencies):out.append('duplicate currency policy')
    for c in p.currencies:
        amount=decimal_record(c.per_transaction_limit)
        if not re.fullmatch(r'[A-Z]{3}',c.iso) or not 0<=c.minor_units<=6 or amount is None or amount<=0:out.append('malformed currency/limit policy')
    if len({a.entity_id for a in b.accounts})!=len(b.accounts) or len({r.entity_id for r in b.recipients})!=len(b.recipients):out.append('duplicate mock entity state')
    registry={e.id:e for e in si.directory.entities} if si.directory else {}
    for account in b.accounts:
        if account.entity_id not in registry or registry[account.entity_id].kind!='ACCOUNT' or not account.owner_id:out.append('bank account registry')
        if len(set(account.supported_currencies))!=len(account.supported_currencies) or len({x.currency for x in account.balances})!=len(account.balances):out.append('duplicate account currency/balance')
        for balance in account.balances:
            value=decimal_record(balance.available)
            if value is None or value<0 or balance.currency not in account.supported_currencies:out.append('malformed balance state')
    for recipient in b.recipients:
        if recipient.entity_id not in registry or registry[recipient.entity_id].kind!=recipient.kind:out.append('bank recipient registry')
    if len({(f.candidate_id,f.anchor_id) for f in b.conditions})!=len(b.conditions):out.append('duplicate condition fact')
    if len({(s.id,s.version) for s in p.trusted_condition_sources})!=len(p.trusted_condition_sources):out.append('duplicate trusted condition source')
    try:
        if date.fromisoformat(b.business_day).isoformat()!=b.business_day:out.append("noncanonical trusted business day")
    except ValueError: out.append('malformed trusted business day')
    if not 1<=p.daily_transaction_count_limit<=100000 or not p.trusted_history_source or not p.trusted_history_version:out.append('malformed velocity policy')
    for c in p.currencies:
        cap=decimal_record(c.daily_outgoing_limit)
        if cap is None or cap<=0:out.append('malformed daily amount cap')
    if len({h.id for h in b.history})!=len(b.history):out.append('duplicate history identity')
    for h in b.history:
        value=decimal_record(h.amount)
        account=next((a for a in b.accounts if a.entity_id==h.source_account_id),None)
        if not h.id or account is None or account.owner_id!=h.user_id or value is None or value<=0 or h.currency not in account.supported_currencies:out.append('malformed history record')
        if (h.source_id,h.source_version)!=(p.trusted_history_source,p.trusted_history_version):out.append('untrusted history source')
        try:
            if date.fromisoformat(h.day).isoformat()!=h.day:out.append("noncanonical history day")
            if date.fromisoformat(h.day)>date.fromisoformat(b.business_day):out.append('future history record')
        except ValueError:out.append('malformed history day')
    return tuple(sorted(set(out)))
