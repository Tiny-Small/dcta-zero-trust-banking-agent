"""Offline scripted lookup and future policy interface; no fallback policy."""
from typing import Protocol
from pydantic import model_validator
from .base import FrozenRecord
from .input import PonderInputSnapshot
from .relations import RelationDecisionBundle
from .serialization import content_sha256

class RelationProposer(Protocol):
    def propose_relations(self, snapshot: PonderInputSnapshot) -> RelationDecisionBundle: ...

class MissingScriptedBundle(LookupError): pass

class ScriptedBundleEntry(FrozenRecord):
    snapshot_sha256: str
    bundle: RelationDecisionBundle

class ScriptedRelationProposer(FrozenRecord):
    entries: tuple[ScriptedBundleEntry, ...]

    @model_validator(mode="after")
    def check_entries(self):
        if len({e.snapshot_sha256 for e in self.entries})!=len(self.entries): raise ValueError("Duplicate scripted snapshot")
        if any(e.snapshot_sha256!=e.bundle.snapshot_sha256 for e in self.entries): raise ValueError("Entry bundle hash mismatch")
        return self

    def propose_relations(self,snapshot):
        key=content_sha256(snapshot)
        for entry in self.entries:
            if entry.snapshot_sha256==key:return entry.bundle
        raise MissingScriptedBundle(key)
