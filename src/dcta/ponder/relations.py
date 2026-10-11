"""Relations supplied by a policy, never discovered by the compiler."""
from typing import Annotated, Literal
from pydantic import Field as Discriminator
from .base import FrozenRecord, Field, ReferenceField, Goal, Context, Disposition, IntentStatus

class FieldTarget(FrozenRecord):
    kind: Literal["FIELD"] = "FIELD"
    frame_id: str
    version_id: str
    field: Field
    mention_id: str | None = None

class FrameTarget(FrozenRecord):
    kind: Literal["FRAME"] = "FRAME"
    frame_id: str

class VersionTarget(FrozenRecord):
    kind: Literal["VERSION"] = "VERSION"
    frame_id: str
    version_id: str

Target = Annotated[FieldTarget | FrameTarget | VersionTarget, Discriminator(discriminator="kind")]

class Claim(FrozenRecord):
    id: str
    support_anchor_ids: tuple[str, ...]
    depends_on: tuple[str, ...] = ()

class FrameClaim(Claim):
    kind: Literal["FRAME"] = "FRAME"
    frame_id: str
    anchor_id: str
    goal: Goal
    version_id: str = "v0"

class FieldOfClaim(Claim):
    kind: Literal["FIELD_OF"] = "FIELD_OF"
    frame_id: str
    version_id: str = "v0"
    mention_id: str
    field: Field

class SharedFieldClaim(Claim):
    kind: Literal["SHARED_FIELD"] = "SHARED_FIELD"
    frame_ids: tuple[str, ...]
    version_id: str = "v0"
    mention_id: str
    field: Field
    mode: Literal["CONTEXTUAL", "DISTRIBUTIVE"]

class DiscourseClaim(Claim):
    kind: Literal["DISCOURSE"] = "DISCOURSE"
    frame_id: str
    version_id: str = "v0"
    context: Context
    disposition: Disposition
    intent_status: IntentStatus

class ReplacesClaim(Claim):
    kind: Literal["REPLACES"] = "REPLACES"
    target: Target
    replacement_frame_id: str
    replacement_version_id: str
    carry_fields: tuple[Field, ...] = ()

class RejectsClaim(Claim):
    kind: Literal["REJECTS"] = "REJECTS"
    target: Target

class RefersToClaim(Claim):
    kind: Literal["REFERS_TO"] = "REFERS_TO"
    reference_anchor_id: str
    carrier_mention_id: str | None
    requested_field: ReferenceField
    antecedent_ids: tuple[str, ...]
    antecedent_version_targets: tuple[VersionTarget, ...] = ()
    allow_noncurrent_antecedent: bool = False

class OperandOfClaim(Claim):
    kind: Literal["OPERAND_OF"] = "OPERAND_OF"
    parent_mention_id: str
    operand_mention_id: str
    parameter: Literal["FRACTION", "PERCENTAGE", "RANGE_ENDPOINT", "ALTERNATIVE_VALUE"]

class AlternativeBranch(FrozenRecord):
    id: str
    frame_ids: tuple[str, ...]
    allocation: Literal["TOTAL_UNALLOCATED", "PER_RECIPIENT", "UNSPECIFIED"] | None = None

class AlternativeClaim(Claim):
    kind: Literal["ALTERNATIVE"] = "ALTERNATIVE"
    group_id: str
    branches: tuple[AlternativeBranch, ...]

class CoordinatedClaim(Claim):
    kind: Literal["COORDINATED"] = "COORDINATED"
    group_id: str
    frame_ids: tuple[str, ...]

class ConditionClaim(Claim):
    kind: Literal["CONDITION"] = "CONDITION"
    frame_id: str
    version_id: str = "v0"
    anchor_id: str

Relation = Annotated[FrameClaim | FieldOfClaim | SharedFieldClaim | DiscourseClaim | ReplacesClaim | RejectsClaim | RefersToClaim | OperandOfClaim | AlternativeClaim | CoordinatedClaim | ConditionClaim, Discriminator(discriminator="kind")]

class RelationDecisionBundle(FrozenRecord):
    schema_version: Literal["ponder-relations-v1"] = "ponder-relations-v1"
    snapshot_sha256: str
    policy_identity: str
    policy_version: str
    claims: tuple[Relation, ...]
