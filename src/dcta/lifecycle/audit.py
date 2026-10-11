"""Append-only in-memory journal; immutable hash-linked records, no secret fields."""
from threading import RLock
from typing import Literal
from dcta.ponder.base import FrozenRecord
from dcta.ponder.serialization import content_sha256

EventKind=Literal['INTERPRETATION_PRODUCED','GROUNDING','CLARIFICATION','SEMANTIC_VALIDATION','BUSINESS_VALIDATION','CONFIRMATION_REQUESTED','CONFIRMATION_ACCEPTED','CONFIRMATION_REJECTED','AUTHORIZATION_ACCEPTED','AUTHORIZATION_DENIED','EXECUTION_ATTEMPTED','EXECUTION_SUCCEEDED','EXECUTION_FAILED','EXECUTION_ALREADY_EXECUTED']

class ArtifactRef(FrozenRecord):
    kind: str
    sha256: str

class AuditRecord(FrozenRecord):
    schema_version: Literal['mock-audit-v1']='mock-audit-v1'
    sequence: int
    previous_sha256: str | None
    event: EventKind
    outcome: str
    artifacts: tuple[ArtifactRef,...]
    causes: tuple[str,...]

class AuditTrail:
    def __init__(self):self._records=();self._lock=RLock()
    @property
    def records(self):return self._records
    def append(self,event,outcome,artifacts=(),causes=()):
        with self._lock:
            known={content_sha256(r) for r in self._records}
            if any(c not in known for c in causes):raise ValueError('Unknown audit cause')
            refs=tuple(ArtifactRef(kind=k,sha256=v) for k,v in artifacts)
            if any(len(r.sha256)!=64 or any(c not in '0123456789abcdef' for c in r.sha256) for r in refs):raise ValueError('Invalid artifact hash')
            record=AuditRecord(sequence=len(self._records),previous_sha256=content_sha256(self._records[-1]) if self._records else None,event=event,outcome=outcome,artifacts=refs,causes=tuple(causes))
            self._records=(*self._records,record)
            return record
    def verify(self):
        known=set();prev=None
        for n,r in enumerate(self._records):
            if r.sequence!=n or r.previous_sha256!=prev or any(c not in known for c in r.causes):return False
            prev=content_sha256(r);known.add(prev)
        return True
