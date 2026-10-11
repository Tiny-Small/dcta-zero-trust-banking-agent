"""Mock cryptographic sign-off for the DCTA demo.

Uses Ed25519 asymmetric digital signatures via the already-installed
`cryptography` library (v50.0.1).  No real banking keys, no real biometric
SDK, no proprietary encryption.

The signature binds together:
  - review_sha256       (the exact confirmed transaction bundle hash)
  - confirmation_sha256 (the accepted confirmation artifact hash)
  - nonce               (a random per-authorization challenge)
  - actor_id            (the authenticated user identity)

The private key is ephemeral, generated per session, and never persisted
or exposed.  The verifier uses only the public key.

Changing ANY of these values invalidates the signature, which the mock
zero-trust gateway checks before allowing execution.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)
from cryptography.exceptions import InvalidSignature


@dataclass(frozen=True)
class SignatureArtifact:
    """Immutable record of a mock authorization signature (Ed25519).

    No private key material is stored here — only the 64-byte Ed25519
    signature and the public key bytes for verification.
    """

    bundle_hash: str  # review_sha256 — exact confirmed transaction
    confirmation_hash: str  # confirmation_sha256
    nonce: str  # random hex challenge (32 chars)
    actor_id: str  # authenticated user identity
    signature: str  # Ed25519 signature hex (128 chars)
    identity: str  # demo signer identity label
    public_key_hex: str  # Ed25519 public key hex (64 chars) for verification

    @property
    def short_signature(self) -> str:
        """First 16 chars for display."""
        return self.signature[:16]

    @property
    def short_bundle(self) -> str:
        return self.bundle_hash[:16]

    @property
    def short_confirmation(self) -> str:
        return self.confirmation_hash[:16]

    @property
    def short_public_key(self) -> str:
        return self.public_key_hex[:16]


def _build_message(bundle_hash: str, confirmation_hash: str, nonce: str, actor_id: str) -> bytes:
    """Construct the deterministic signed message from bound values."""
    return f"{bundle_hash}:{confirmation_hash}:{nonce}:{actor_id}".encode()


class DemoSigner:
    """Synthetic, ephemeral, demo-only Ed25519 signing identity.

    The private key is generated per-session with Ed25519PrivateKey.generate()
    and never persisted or exposed.  This is NOT a real banking key — it is
    a synthetic keypair used to demonstrate asymmetric cryptographic binding.

    The verifier (DemoVerifier) uses only the public key, which is safe to
    share.  The private key never leaves this object.
    """

    IDENTITY = "demo-signer:synthetic"

    def __init__(self):
        self._private_key: Ed25519PrivateKey = Ed25519PrivateKey.generate()
        self._public_key: Ed25519PublicKey = self._private_key.public_key()
        self.identity = self.IDENTITY
        self._public_key_bytes = self._public_key.public_bytes(
            encoding=Encoding.Raw,
            format=PublicFormat.Raw,
        )
        self.public_key_hex = self._public_key_bytes.hex()

    def sign(
        self,
        bundle_hash: str,
        confirmation_hash: str,
        actor_id: str,
    ) -> SignatureArtifact:
        """Create a signature artifact binding to the exact confirmed bundle."""
        nonce = secrets.token_hex(16)
        msg = _build_message(bundle_hash, confirmation_hash, nonce, actor_id)
        sig_bytes = self._private_key.sign(msg)
        return SignatureArtifact(
            bundle_hash=bundle_hash,
            confirmation_hash=confirmation_hash,
            nonce=nonce,
            actor_id=actor_id,
            signature=sig_bytes.hex(),
            identity=self.identity,
            public_key_hex=self.public_key_hex,
        )

    def verify(
        self,
        artifact: SignatureArtifact,
        bundle_hash: str,
        confirmation_hash: str,
        actor_id: str,
    ) -> bool:
        """Verify that a signature artifact matches the given bindings.

        Uses the Ed25519 public key only — no private key needed.
        """
        msg = _build_message(
            bundle_hash, confirmation_hash, artifact.nonce, actor_id
        )
        try:
            self._public_key.verify(
                bytes.fromhex(artifact.signature), msg
            )
            return True
        except (InvalidSignature, ValueError):
            return False


class DemoVerifier:
    """Stateless verifier using only a public key.

    This mirrors a real gateway verifier: it has the public key but
    never the private key.  It can verify signatures but cannot create them.
    """

    def __init__(self, public_key_hex: str):
        self._public_key = Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(public_key_hex)
        )

    def verify(
        self,
        artifact: SignatureArtifact,
        bundle_hash: str,
        confirmation_hash: str,
        actor_id: str,
    ) -> bool:
        """Verify an Ed25519 signature using only the public key."""
        msg = _build_message(
            bundle_hash, confirmation_hash, artifact.nonce, actor_id
        )
        try:
            self._public_key.verify(
                bytes.fromhex(artifact.signature), msg
            )
            return True
        except (InvalidSignature, ValueError):
            return False
