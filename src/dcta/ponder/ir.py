"""Inert, immutable interpretation IR. No bank or execution capability."""
from typing import Literal
from .base import FrozenRecord, Field, ReferenceField, Goal, Context, Disposition, IntentStatus
from .input import PonderInputSnapshot
from .relations import RelationDecisionBundle, AlternativeBranch, Target, VersionTarget

class CompilationIssue(FrozenRecord):
    category: str
    affected_ids: tuple[str, ...] = ()
    support_ids: tuple[str, ...] = ()
    detail: str = ""
    severity: Literal["ERROR", "UNRESOLVED", "DIAGNOSTIC"] = "ERROR"

class IntegrityReport(FrozenRecord):
    issues: tuple[CompilationIssue, ...] = ()
    blocked_relation_ids: tuple[str, ...] = ()
    affected_frame_ids: tuple[str, ...] = ()
    global_error: bool = False

class FieldBinding(FrozenRecord):
    field: Field
    status: Literal["BOUND", "MISSING", "UNRESOLVED", "ALTERNATIVE", "REJECTED"]
    mention_ids: tuple[str, ...] = ()
    support_ids: tuple[str, ...] = ()
    uncertainty_ids: tuple[str, ...] = ()
    shared_mode: Literal["CONTEXTUAL", "DISTRIBUTIVE"] | None = None

class OperationCandidate(FrozenRecord):
    id: str
    frame_id: str
    version_id: str
    goal: Goal
    bindings: tuple[FieldBinding, ...]
    support_ids: tuple[str, ...]
    snapshot_sha256: str
    bundle_sha256: str

class CandidateGroup(FrozenRecord):
    id: str
    kind: Literal["EXCLUSIVE", "COORDINATED"]
    member_frame_ids: tuple[str, ...]
    branches: tuple[AlternativeBranch, ...] = ()
    support_ids: tuple[str, ...]

class IntentProjection(FrozenRecord):
    candidate_id: str
    context: Context = "unknown"
    disposition: Disposition = "unresolved"
    intent_status: IntentStatus = "UNRESOLVED"
    support_ids: tuple[str, ...] = ()
    condition_anchor_ids: tuple[str, ...] = ()

class RevisionRelation(FrozenRecord):
    id: str
    kind: Literal["REPLACES", "REJECTS"]
    target: Target
    replacement_candidate_id: str | None = None
    carry_fields: tuple[Field, ...] = ()
    support_ids: tuple[str, ...]

class ValueExpression(FrozenRecord):
    id: str
    kind: Literal["LITERAL_SOURCE", "DEPENDENT_SOURCE", "REFERENCE", "RANGE", "ALTERNATIVE", "UNRESOLVED"]
    mention_id: str | None
    operand_ids: tuple[str, ...] = ()
    basis_anchor_ids: tuple[str, ...] = ()
    antecedent_ids: tuple[str, ...] = ()
    antecedent_version_targets: tuple[VersionTarget, ...] = ()
    support_ids: tuple[str, ...] = ()

class UnresolvedReference(FrozenRecord):
    id: str
    anchor_id: str
    carrier_mention_id: str | None
    requested_field: ReferenceField
    antecedent_ids: tuple[str, ...]
    antecedent_version_targets: tuple[VersionTarget, ...] = ()
    reason: Literal["NO_ANTECEDENT", "MULTIPLE_ANTECEDENTS", "UNSUPPORTED_BASIS", "MISSING_CARRIER"]
    support_ids: tuple[str, ...]

class BindingAssembly(FrozenRecord):
    candidates: tuple[OperationCandidate, ...] = ()
    groups: tuple[CandidateGroup, ...] = ()
    issues: tuple[CompilationIssue, ...] = ()

class DiscourseAssembly(BindingAssembly):
    projections: tuple[IntentProjection, ...] = ()
    revisions: tuple[RevisionRelation, ...] = ()

class ExpressionAssembly(FrozenRecord):
    expressions: tuple[ValueExpression, ...] = ()
    references: tuple[UnresolvedReference, ...] = ()
    issues: tuple[CompilationIssue, ...] = ()

class PonderCompilation(DiscourseAssembly):
    schema_version: Literal["ponder-ir-v1"] = "ponder-ir-v1"
    snapshot_sha256: str
    bundle_sha256: str
    status: Literal["OK", "PARTIAL_INPUT", "CONTRACT_ERROR"] = "OK"
    input_snapshot: PonderInputSnapshot | None = None
    relation_bundle: RelationDecisionBundle | None = None
    expressions: tuple[ValueExpression, ...] = ()
    references: tuple[UnresolvedReference, ...] = ()
    current_candidate_ids: tuple[str, ...] = ()
    requested_group_ids: tuple[str, ...] = ()
