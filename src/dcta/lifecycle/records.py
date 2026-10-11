from typing import Literal
from dcta.ponder.base import FrozenRecord
from dcta.business.input import BusinessValidationInput
from dcta.business.records import BusinessValidationResult
from dcta.business.gate import BusinessGate

class Transfer(FrozenRecord):
    candidate_id: str
    version_id: str
    candidate_sha256: str
    source_account_id: str
    source_label: str
    target_entity_id: str
    target_label: str
    target_kind: Literal['PERSON','ACCOUNT']
    currency: str
    amount: str

class Review(FrozenRecord):
    schema_version: Literal['exact-bundle-review-v1']='exact-bundle-review-v1'
    data: BusinessValidationInput
    business_result: BusinessValidationResult
    business_gate: BusinessGate
    transfers: tuple[Transfer,...]
    rendered_payload: str
    rendered_payload_sha256: str

class Confirmation(FrozenRecord):
    generation: int
    id: str
    status: Literal['ACCEPTED','REJECTED']
    actor_id: str
    review_sha256: str
    rendered_payload_sha256: str
    request_event_sha256: str
    authorized: Literal[False]=False

class Authorization(FrozenRecord):
    generation: int
    request_event_sha256: str
    id: str
    status: Literal['ACCEPTED','DENIED']
    actor_id: str
    review_sha256: str
    confirmation_sha256: str
    confirmation_event_sha256: str
    idempotency_key: str

class Receipt(FrozenRecord):
    schema_version: Literal['mock-execution-receipt-v1']='mock-execution-receipt-v1'
    authorization_sha256: str
    confirmation_sha256: str
    review_sha256: str
    idempotency_key: str
    transfers: tuple[Transfer,...]
    bank_before_sha256: str
    bank_after_sha256: str
    bank_after_revision: int

class ExecutionResult(FrozenRecord):
    status: Literal['SUCCEEDED','ALREADY_EXECUTED','FAILED']
    receipt: Receipt | None=None
    code: str
