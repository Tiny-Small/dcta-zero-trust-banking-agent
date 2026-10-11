"""Versioned synthetic bank/policy records and inert business results."""
from typing import Literal
from dcta.ponder.base import FrozenRecord
from dcta.ponder.input import EvidenceRef
from dcta.validation.records import ValidationTarget

Status=Literal['PASS','NEEDS_CLARIFICATION','BLOCKED','CONTRACT_ERROR']
VERSION='mock-business-risk-v2'

class Balance(FrozenRecord):
    currency: str
    available: str

class BankAccount(FrozenRecord):
    entity_id: str
    owner_id: str
    active: bool
    usable: bool
    supported_currencies: tuple[str,...]
    balances: tuple[Balance,...]

class BankRecipient(FrozenRecord):
    entity_id: str
    kind: Literal['PERSON','ACCOUNT']
    active: bool
    supported_currencies: tuple[str,...]

class ConditionFact(FrozenRecord):
    candidate_id: str
    candidate_sha256: str
    anchor_id: str
    anchor_sha256: str
    state: Literal['SATISFIED','UNSATISFIED','UNKNOWN']
    source_id: str
    source_version: str

class HistoryEntry(FrozenRecord):
    id: str
    user_id: str
    day: str
    source_account_id: str
    currency: str
    amount: str
    source_id: str
    source_version: str

class FundsLedgerEntry(FrozenRecord):
    candidate_id: str
    source_account_id: str
    currency: str
    requested: str
    before: str
    after: str
    accepted: bool

class MockBankState(FrozenRecord):
    version: str
    revision: int
    snapshot_id: str
    authenticated_user_id: str
    directory_sha256: str
    accounts: tuple[BankAccount,...]
    recipients: tuple[BankRecipient,...]
    conditions: tuple[ConditionFact,...]=()
    business_day: str="2026-10-08"
    history: tuple[HistoryEntry,...]=()

class CurrencyRule(FrozenRecord):
    iso: str
    minor_units: int
    per_transaction_limit: str
    daily_outgoing_limit: str="1500.00"

class TrustedConditionSource(FrozenRecord):
    id: str
    version: str

class MockBankPolicy(FrozenRecord):
    version: str
    supported_goals: tuple[Literal['transfer','payment'],...]
    currencies: tuple[CurrencyRule,...]
    trusted_condition_sources: tuple[TrustedConditionSource,...]
    daily_transaction_count_limit: int=10
    trusted_history_source: str="mock:transaction-ledger"
    trusted_history_version: str="v1"
    rule_set: Literal['owned-active-source-positive-exact-amount-bundle-funds-v1']='owned-active-source-positive-exact-amount-bundle-funds-v1'

class BusinessCondition(FrozenRecord):
    candidate_id: str
    version_id: str
    candidate_sha256: str
    anchor_id: str
    anchor_sha256: str
    evidence: EvidenceRef

class BusinessBundle(FrozenRecord):
    compilation_sha256: str
    targets: tuple[ValidationTarget,...]
    grounding_sha256: str | None
    semantic_input_sha256: str

class BusinessFinding(FrozenRecord):
    candidate_id: str | None
    version_id: str | None
    candidate_sha256: str | None
    field: str
    rule_id: str
    code: str
    result: Status
    observed: str
    explanation: str
    semantic_evidence: tuple[EvidenceRef,...]
    mock_record_ids: tuple[str,...]
    mock_evidence_json: str
    mock_evidence_sha256: str
    bank_sha256: str
    policy_sha256: str
    semantic_decision_sha256: str

class ClarificationRequirement(FrozenRecord):
    candidate_id: str
    version_id: str
    field: str
    reason: str
    prompt: str
    choices: tuple[str,...]=()
    requires_new_semantic_version: Literal[True]=True
    requires_semantic_revalidation: Literal[True]=True

class OperationBusinessResult(FrozenRecord):
    target: ValidationTarget
    status: Status
    findings: tuple[BusinessFinding,...]
    clarifications: tuple[ClarificationRequirement,...]=()

class BusinessValidationResult(FrozenRecord):
    schema_version: Literal['business-validation-result-v1']='business-validation-result-v1'
    validator_version: str=VERSION
    status: Status
    business_input_sha256: str
    bundle_sha256: str
    compilation_sha256: str
    grounding_revision: int | None
    grounding_sha256: str | None
    semantic_input_sha256: str
    semantic_decision_sha256: str
    semantic_gate_sha256: str
    bank_sha256: str
    bank_version: str
    bank_revision: int
    policy_sha256: str
    policy_version: str
    funds_ledger: tuple[FundsLedgerEntry,...]=()
    operations: tuple[OperationBusinessResult,...]
    findings: tuple[BusinessFinding,...]
    confirmed: Literal[False]=False
    authorized: Literal[False]=False
    executable: Literal[False]=False
