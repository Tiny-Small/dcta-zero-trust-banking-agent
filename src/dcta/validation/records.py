"""Immutable findings, independent observations and validation decisions."""
import hashlib,json
from typing import Literal
from dcta.ponder.base import FrozenRecord
from dcta.ponder.input import EvidenceRef

Result=Literal['MATCH','DISCREPANCY','UNRESOLVED','CONTRACT_ERROR']
VERSION='semantic-validator-v2'

def json_text(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def string_hash(value):return hashlib.sha256(value.encode()).hexdigest()

class ValidationTarget(FrozenRecord):
    candidate_id: str
    frame_id: str
    version_id: str
    candidate_sha256: str

class Finding(FrozenRecord):
    id: str
    result: Result
    kind: str
    field: str
    candidate_id: str | None=None
    version_id: str | None=None
    proposed: str
    evidence_ids: tuple[str,...]
    evidence: tuple[EvidenceRef,...]
    reason: str

class SemanticCheck(FrozenRecord):
    id: str
    candidate_id: str | None
    version_id: str | None
    field: str
    result: Literal['MATCH','DISCREPANCY','UNRESOLVED']
    evidence_id: str

class ValidatorObservation(FrozenRecord):
    mode: Literal['DETERMINISTIC','MODEL']
    validation_input_sha256: str
    validator_version: str=VERSION
    configured_model: str | None=None
    request_json: str
    request_sha256: str
    response_json: str
    response_sha256: str

class ValidationDecision(FrozenRecord):
    schema_version: Literal['semantic-validation-decision-v1']='semantic-validation-decision-v1'
    result: Result
    validation_input_sha256: str
    targets: tuple[ValidationTarget,...]
    grounding_sha256: str | None
    grounding_revision: int | None
    observation_sha256: str
    validator_version: str=VERSION
    observation: ValidatorObservation
    checks: tuple[SemanticCheck,...]
    findings: tuple[Finding,...]
