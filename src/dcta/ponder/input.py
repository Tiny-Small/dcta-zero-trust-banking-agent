"""Supplied mention transport only. No extractor, gold or intent policy."""
import hashlib
from typing import Literal
from .base import FrozenRecord, Role, Field, Goal

class SourceSnapshot(FrozenRecord):
    id: str
    text: str
    text_sha256: str
    turn: str = ""
    revision: str = ""
    finality: Literal["FINAL", "PARTIAL", "UNKNOWN"] = "FINAL"

    @classmethod
    def from_text(cls, id: str, text: str, **kwargs):
        return cls(id=id, text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest(), **kwargs)

class EvidenceRef(FrozenRecord):
    source_id: str
    start: int
    end: int
    text: str

class NormalizedValue(FrozenRecord):
    kind: str
    value: str

class CandidateProvenance(FrozenRecord):
    candidate_types: tuple[str, ...] = ()
    generators: tuple[str, ...] = ()
    producer_record_hash: str = ""

class SemanticMention(FrozenRecord):
    id: str
    candidate_id: str
    role: Role
    evidence: EvidenceRef
    normalized: NormalizedValue | None = None
    provenance: CandidateProvenance = CandidateProvenance()
    origin: Literal["CANONICAL", "RETAINED_COMPOUND", "PRIOR"] = "CANONICAL"

class RelationalAnchor(FrozenRecord):
    id: str
    kind: Literal["PREDICATE", "COORDINATION", "CORRECTION", "NEGATION", "DISCOURSE", "REFERENCE", "BASIS", "CONDITION", "NESTING"]
    evidence: EvidenceRef

class PingProjection(FrozenRecord):
    mention_id: str
    producer_scope: Literal["ROOT", "NESTED_DATA", "NESTED_OPERAND", "ROOT_EMITTED", "UNKNOWN", "EXCLUDED_BY_SCOPE"]
    emitted_root: bool
    parent_mention_id: str | None = None
    status: str = "SUPPLIED"
    support_ids: tuple[str, ...] = ()
    scope_decision: str | None = None

class RetainedCompound(FrozenRecord):
    mention_id: str
    structural_support: tuple[str, ...] = ()

class UpstreamDiagnostic(FrozenRecord):
    id: str
    category: str
    affected_ids: tuple[str, ...] = ()
    detail: str = ""

class PriorField(FrozenRecord):
    field: Field
    mention_ids: tuple[str, ...]

class PriorVersion(FrozenRecord):
    id: str
    frame_id: str
    version_id: str
    goal: Goal
    fields: tuple[PriorField, ...]
    original_content_sha256: str

class PriorContext(FrozenRecord):
    sources: tuple[SourceSnapshot, ...] = ()
    semantic_mentions: tuple[SemanticMention, ...] = ()
    relational_anchors: tuple[RelationalAnchor, ...] = ()
    ping_projection: tuple[PingProjection, ...] = ()
    versions: tuple[PriorVersion, ...] = ()

class PonderInputSnapshot(FrozenRecord):
    schema_version: Literal["ponder-input-v1"] = "ponder-input-v1"
    current_source: SourceSnapshot
    semantic_mentions: tuple[SemanticMention, ...]
    relational_anchors: tuple[RelationalAnchor, ...] = ()
    ping_projection: tuple[PingProjection, ...] = ()
    retained_compounds: tuple[RetainedCompound, ...] = ()
    upstream_diagnostics: tuple[UpstreamDiagnostic, ...] = ()
    prior_context: PriorContext | None = None
    extractor_identity: str
    extractor_sha256: str
    contract_version: str
    input_status: Literal["COMPLETE", "PARTIAL_INPUT"] = "COMPLETE"

def snapshot_from_records(**kwargs) -> PonderInputSnapshot:
    return PonderInputSnapshot.model_validate(kwargs)

def copy_extractor_input(payload: bytes, *, source_id: str, extractor_identity: str, extractor_sha256: str) -> PonderInputSnapshot:
    """Copy the versioned ponder-input-v1 producer envelope, not a saved-run file.

    The transport has explicit classified mentions, compounds and supplied Ping
    projections. Consumers must provide them; no raw candidate is promoted here.
    """
    result = PonderInputSnapshot.model_validate_json(payload)
    if (result.current_source.id, result.extractor_identity, result.extractor_sha256) != (source_id, extractor_identity, extractor_sha256):
        raise ValueError("Producer identity mismatch")
    return result
