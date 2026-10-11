"""Canonical unordered record tables. Ordering comes only from explicit links."""
import hashlib
import json
from .base import FrozenRecord

def _canonical(value):
    if isinstance(value, dict):
        return {k: _canonical(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return sorted((_canonical(v) for v in value), key=lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return value

def canonical_bytes(record: FrozenRecord) -> bytes:
    return json.dumps(_canonical(record.model_dump(mode="json")), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def content_sha256(record: FrozenRecord) -> str:
    return hashlib.sha256(canonical_bytes(record)).hexdigest()

def decode_input(payload: bytes):
    from .input import PonderInputSnapshot
    return PonderInputSnapshot.model_validate_json(payload)


def decode_bundle(payload: bytes):
    from .relations import RelationDecisionBundle
    return RelationDecisionBundle.model_validate_json(payload)

def decode_compilation(payload: bytes):
    from .ir import PonderCompilation
    return PonderCompilation.model_validate_json(payload)
