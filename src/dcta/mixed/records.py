from typing import Literal
from dcta.ponder.base import FrozenRecord
from dcta.ponder.input import EvidenceRef
from dcta.ponder.ir import PonderCompilation
from dcta.ponder.relations import RelationDecisionBundle

Action=Literal['BUY','SELL','UNSPECIFIED']

class ActionClaim(FrozenRecord):
    frame_id: str
    anchor_id: str
    action: Action
    evidence: EvidenceRef

class MixedRelationDecisionBundle(FrozenRecord):
    schema_version: Literal['mixed-relations-v1']='mixed-relations-v1'
    core: RelationDecisionBundle
    action_claims: tuple[ActionClaim,...]

class InvestmentAction(FrozenRecord):
    candidate_id: str
    frame_id: str
    version_id: str
    candidate_sha256: str
    snapshot_sha256: str
    relation_bundle_sha256: str
    action: Action
    anchor_id: str
    evidence: EvidenceRef

class MixedInterpretation(FrozenRecord):
    schema_version: Literal['mixed-interpretation-v1']='mixed-interpretation-v1'
    compilation: PonderCompilation
    relations: MixedRelationDecisionBundle
    actions: tuple[InvestmentAction,...]
