from typing import Literal
from dcta.ponder.base import FrozenRecord
from dcta.ponder.relations import Relation

class Limits(FrozenRecord):
    max_mentions:int=12
    max_predicates:int=3
    max_frames:int=16
    max_packets:int=128

class FrameSpec(FrozenRecord):
    frame_id:str
    anchor_id:str

class Packet(FrozenRecord):
    id:str
    kind:str
    frames:tuple[FrameSpec,...]
    claims:tuple[Relation,...]=()

class Registry(FrozenRecord):
    snapshot_sha256:str
    status:Literal["READY","UNSUPPORTED","LIMIT_EXCEEDED"]
    reason:str=""
    packets:tuple[Packet,...]=()
    counts:tuple[tuple[str,int],...]=()
