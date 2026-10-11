"""Tests for the Ed25519 cryptographic sign-off.

Verifies:
  - Signature binds to exact bundle hash + confirmation hash + nonce + actor
  - Changing any component invalidates the signature
  - Public-key-only verification works (DemoVerifier has no private key)
  - Tampered signature is rejected
  - No private key material is exposed in the artifact
  - Stale version (different bundle) is rejected
"""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
_src = _root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from demo_ui.crypto import DemoSigner, DemoVerifier, SignatureArtifact


def test_signature_binds_to_bundle_hash():
    signer = DemoSigner()
    sig = signer.sign("a" * 64, "conf_hash", "actor_1")
    assert signer.verify(sig, "a" * 64, "conf_hash", "actor_1")
    assert not signer.verify(sig, "b" * 64, "conf_hash", "actor_1")


def test_signature_binds_to_confirmation_hash():
    signer = DemoSigner()
    sig = signer.sign("a" * 64, "conf_a", "actor_1")
    assert signer.verify(sig, "a" * 64, "conf_a", "actor_1")
    assert not signer.verify(sig, "a" * 64, "conf_b", "actor_1")


def test_signature_binds_to_actor():
    signer = DemoSigner()
    sig = signer.sign("a" * 64, "conf_a", "actor_1")
    assert not signer.verify(sig, "a" * 64, "conf_a", "actor_2")


def test_signature_has_random_nonce():
    signer = DemoSigner()
    sig1 = signer.sign("a" * 64, "conf_a", "actor_1")
    sig2 = signer.sign("a" * 64, "conf_a", "actor_1")
    assert sig1.nonce != sig2.nonce
    assert sig1.signature != sig2.signature
    assert signer.verify(sig1, "a" * 64, "conf_a", "actor_1")
    assert signer.verify(sig2, "a" * 64, "conf_a", "actor_1")


def test_artifact_does_not_expose_private_key():
    signer = DemoSigner()
    sig = signer.sign("a" * 64, "conf_a", "actor_1")
    assert not hasattr(sig, "_private_key")
    assert not hasattr(sig, "private_key")
    assert not hasattr(sig, "_secret")
    assert not hasattr(sig, "secret")
    assert sig.identity == "demo-signer:synthetic"
    assert len(sig.public_key_hex) == 64


def test_different_signers_produce_different_keys():
    signer_a = DemoSigner()
    signer_b = DemoSigner()
    sig_a = signer_a.sign("a" * 64, "conf_a", "actor_1")
    assert signer_a.public_key_hex != signer_b.public_key_hex
    assert not signer_b.verify(sig_a, "a" * 64, "conf_a", "actor_1")


def test_public_key_only_verifier_works():
    """DemoVerifier has only the public key and can verify but not sign."""
    signer = DemoSigner()
    sig = signer.sign("a" * 64, "conf_a", "actor_1")
    verifier = DemoVerifier(signer.public_key_hex)
    assert not hasattr(verifier, "_private_key")
    assert verifier.verify(sig, "a" * 64, "conf_a", "actor_1")
    assert not verifier.verify(sig, "b" * 64, "conf_a", "actor_1")


def test_tampered_signature_rejected():
    signer = DemoSigner()
    sig = signer.sign("a" * 64, "conf_a", "actor_1")
    verifier = DemoVerifier(signer.public_key_hex)
    tampered = SignatureArtifact(
        bundle_hash=sig.bundle_hash,
        confirmation_hash=sig.confirmation_hash,
        nonce=sig.nonce,
        actor_id=sig.actor_id,
        signature="0" * 128,
        identity=sig.identity,
        public_key_hex=sig.public_key_hex,
    )
    assert not verifier.verify(tampered, "a" * 64, "conf_a", "actor_1")


def test_stale_version_rejected():
    """A signature for bundle v1 must not verify for bundle v2."""
    signer = DemoSigner()
    v1_hash = "a" * 64
    v2_hash = "b" * 64
    sig_v1 = signer.sign(v1_hash, "conf_a", "actor_1")
    verifier = DemoVerifier(signer.public_key_hex)
    assert verifier.verify(sig_v1, v1_hash, "conf_a", "actor_1")
    assert not verifier.verify(sig_v1, v2_hash, "conf_a", "actor_1")


def test_short_hashes_for_display():
    signer = DemoSigner()
    sig = signer.sign("a" * 64, "b" * 64, "actor_1")
    assert len(sig.short_signature) == 16
    assert len(sig.short_bundle) == 16
    assert len(sig.short_confirmation) == 16
    assert len(sig.short_public_key) == 16


def test_ed25519_signature_length():
    """Ed25519 signatures are exactly 64 bytes = 128 hex chars."""
    signer = DemoSigner()
    sig = signer.sign("a" * 64, "conf_a", "actor_1")
    assert len(sig.signature) == 128
    assert len(sig.public_key_hex) == 64
