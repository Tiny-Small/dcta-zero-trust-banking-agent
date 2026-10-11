"""Versioned, public-key-only authorization boundary for the submission demo.

The frozen MixedGateway is private to this adapter. Its historical API does
not know about Ed25519; callers of this public demo boundary must provide
exact, current signing evidence before either backend method is reached.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from threading import RLock

from dcta.lifecycle.errors import LifecycleError
from dcta.lifecycle.records import Authorization, Confirmation
from dcta.mixed.gateway import MixedExecutionResult, MixedGateway
from dcta.mixed.review import MixedReview, verify_review
from dcta.ponder.serialization import content_sha256

from .crypto import DemoVerifier, SignatureArtifact


@dataclass(frozen=True)
class BiometricProof:
    """Proof that the explicit simulated biometric action occurred."""

    token: str
    confirmation_hash: str
    generation: int
    actor_id: str
    schema_version: str = "simulated-biometric-proof-v1"


@dataclass(frozen=True)
class VerifiedSignature:
    """Public-key verification result for the current exact version."""

    token: str
    signature: SignatureArtifact
    confirmation_hash: str
    biometric_token: str
    generation: int
    schema_version: str = "verified-demo-signature-v1"


@dataclass(frozen=True)
class SignedAuthorization:
    """Version-bound capability issued only after signature verification."""

    token: str
    authorization: Authorization
    confirmation: Confirmation
    signature: SignatureArtifact
    biometric_token: str
    schema_version: str = "signed-demo-authorization-v1"


@dataclass(frozen=True)
class SignedExecutionResult:
    result: MixedExecutionResult
    signature_verified: bool
    authorization_accepted: bool


class SignedExecutionGateway:
    """The only authorize/execute interface exposed to the demo UI."""

    schema_version = "signed-execution-gateway-v1"

    def __init__(self, backend: MixedGateway, public_key_hex: str):
        if not isinstance(backend, MixedGateway):
            raise TypeError("MixedGateway required")
        self._backend = backend
        self._public_key_hex = public_key_hex
        self._verifier = DemoVerifier(public_key_hex)
        self._biometrics: dict[str, BiometricProof] = {}
        self._signatures: dict[str, VerifiedSignature] = {}
        self._authorizations: dict[str, SignedAuthorization] = {}
        self._lock = RLock()

    @property
    def bank(self):
        return self._backend.bank

    @property
    def audit(self):
        return self._backend.audit

    @property
    def simulated_investments(self):
        return self._backend.simulated_investments

    @property
    def receipts(self):
        return self._backend.receipts

    def _current_confirmation(self, confirmation: Confirmation) -> bool:
        if type(confirmation) is not Confirmation or confirmation.status != "ACCEPTED":
            return False
        backend = self._backend
        registered = backend._confirmations.get(confirmation.id)
        requested = backend._requests.get(confirmation.review_sha256)
        return bool(
            registered is not None
            and registered[0] == confirmation
            and requested is not None
            and requested[1] == confirmation.request_event_sha256
            and backend._active == confirmation.review_sha256
            and backend._generation == confirmation.generation
            and confirmation.actor_id == backend.bank.authenticated_user_id
        )

    def is_current_confirmation(self, confirmation: Confirmation | None) -> bool:
        with self._lock:
            return self._current_confirmation(confirmation)

    def confirm(self, review: MixedReview, *, accepted: bool, actor_id: str):
        with self._lock:
            confirmation = self._backend.confirm(
                review, accepted=accepted, actor_id=actor_id
            )
            if not accepted:
                self._revoke()
            return confirmation

    def reject(self, review: MixedReview, *, actor_id: str):
        """Record rejection, then advance generation to revoke prior authority."""
        with self._lock:
            if any(
                cap.authorization.id in self._backend._executions
                for cap in self._authorizations.values()
            ):
                raise LifecycleError("ALREADY_EXECUTED")
            return self.confirm(review, accepted=False, actor_id=actor_id)

    def _revoke(self):
        self._backend.invalidate()
        self._biometrics.clear()
        self._signatures.clear()
        self._authorizations.clear()

    def invalidate(self):
        with self._lock:
            self._revoke()

    def verify_biometric(self, confirmation: Confirmation) -> BiometricProof:
        """Issue evidence only when the user explicitly takes this mock step."""
        with self._lock:
            if not self._current_confirmation(confirmation):
                raise LifecycleError("STALE_OR_UNACCEPTED_CONFIRMATION")
            proof = BiometricProof(
                token=secrets.token_hex(16),
                confirmation_hash=content_sha256(confirmation),
                generation=confirmation.generation,
                actor_id=confirmation.actor_id,
            )
            self._biometrics[proof.token] = proof
            return proof

    def is_current_biometric(
        self, proof: BiometricProof | None, confirmation: Confirmation | None
    ) -> bool:
        with self._lock:
            return bool(
                type(proof) is BiometricProof
                and self._biometrics.get(proof.token) == proof
                and self._current_confirmation(confirmation)
                and proof.confirmation_hash == content_sha256(confirmation)
                and proof.generation == confirmation.generation
                and proof.actor_id == confirmation.actor_id
            )

    def _check_signature(
        self, signature: SignatureArtifact | None, confirmation: Confirmation
    ) -> None:
        if type(signature) is not SignatureArtifact:
            raise LifecycleError("SIGNATURE_REQUIRED")
        if (
            signature.bundle_hash != confirmation.review_sha256
            or signature.confirmation_hash != content_sha256(confirmation)
            or signature.actor_id != confirmation.actor_id
            or signature.public_key_hex != self._public_key_hex
            or not isinstance(signature.nonce, str)
            or re.fullmatch(r"[0-9a-f]{32}", signature.nonce) is None
            or not isinstance(signature.signature, str)
            or re.fullmatch(r"[0-9a-f]{128}", signature.signature) is None
            or not self._verifier.verify(
                signature,
                confirmation.review_sha256,
                content_sha256(confirmation),
                confirmation.actor_id,
            )
        ):
            raise LifecycleError("INVALID_OR_STALE_SIGNATURE")

    def _check_inputs(
        self,
        review: MixedReview,
        confirmation: Confirmation,
        biometric: BiometricProof | None,
        signature: SignatureArtifact | None,
        actor_id: str,
    ) -> None:
        if not self._current_confirmation(confirmation):
            raise LifecycleError("STALE_OR_UNACCEPTED_CONFIRMATION")
        if type(review) is not MixedReview:
            raise LifecycleError("EXACT_BUSINESS_REVIEW_REQUIRED")
        review_hash = content_sha256(review)
        requested = self._backend._requests.get(review_hash)
        if (
            review_hash != confirmation.review_sha256
            or requested is None
            or requested[0] != review
            or review.business_gate.state != "ELIGIBLE_FOR_CONFIRMATION"
            or actor_id != confirmation.actor_id
        ):
            raise LifecycleError("EXACT_BUSINESS_REVIEW_REQUIRED")
        verify_review(review)
        if not self.is_current_biometric(biometric, confirmation):
            raise LifecycleError("BIOMETRIC_PROOF_REQUIRED")
        self._check_signature(signature, confirmation)

    def verify_signature(
        self,
        review: MixedReview,
        confirmation: Confirmation,
        biometric: BiometricProof | None,
        signature: SignatureArtifact | None,
    ) -> VerifiedSignature:
        with self._lock:
            self._check_inputs(
                review, confirmation, biometric, signature, confirmation.actor_id
            )
            proof = VerifiedSignature(
                token=secrets.token_hex(16),
                signature=signature,
                confirmation_hash=content_sha256(confirmation),
                biometric_token=biometric.token,
                generation=confirmation.generation,
            )
            self._signatures[proof.token] = proof
            return proof

    def is_current_signature(
        self,
        proof: VerifiedSignature | None,
        confirmation: Confirmation | None,
        biometric: BiometricProof | None,
        signature: SignatureArtifact | None,
    ) -> bool:
        with self._lock:
            if (
                type(proof) is not VerifiedSignature
                or self._signatures.get(proof.token) != proof
                or proof.signature != signature
                or not self.is_current_biometric(biometric, confirmation)
                or proof.confirmation_hash != content_sha256(confirmation)
                or proof.biometric_token != biometric.token
                or proof.generation != confirmation.generation
            ):
                return False
            try:
                self._check_signature(signature, confirmation)
            except LifecycleError:
                return False
            return True

    def authorize(
        self,
        review: MixedReview,
        confirmation: Confirmation,
        biometric: BiometricProof | None,
        signature: SignatureArtifact | None,
        *,
        actor_id: str,
        idempotency_key: str,
        verification: VerifiedSignature | None = None,
    ) -> SignedAuthorization:
        with self._lock:
            self._check_inputs(review, confirmation, biometric, signature, actor_id)
            if not self.is_current_signature(
                verification, confirmation, biometric, signature
            ):
                raise LifecycleError("VERIFIED_SIGNATURE_REQUIRED")
            if any(
                cap.confirmation == confirmation for cap in self._authorizations.values()
            ):
                raise LifecycleError("ALREADY_AUTHORIZED")
            # All signed checks precede the frozen backend authorization call.
            authorization = self._backend.authorize(
                confirmation,
                accepted=True,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
            )
            capability = SignedAuthorization(
                token=secrets.token_hex(16),
                authorization=authorization,
                confirmation=confirmation,
                signature=signature,
                biometric_token=biometric.token,
            )
            self._authorizations[capability.token] = capability
            return capability

    def _check_capability(
        self,
        capability: SignedAuthorization | None,
        signature: SignatureArtifact | None,
    ) -> None:
        if (
            type(capability) is not SignedAuthorization
            or self._authorizations.get(capability.token) != capability
            or signature != capability.signature
            or not self._current_confirmation(capability.confirmation)
        ):
            raise LifecycleError("SIGNED_AUTHORIZATION_REQUIRED_OR_STALE")
        authorization = capability.authorization
        registered = self._backend._authorizations.get(authorization.id)
        if (
            registered is None
            or registered[0] != authorization
            or authorization.status != "ACCEPTED"
            or authorization.confirmation_sha256
            != content_sha256(capability.confirmation)
            or authorization.review_sha256 != capability.confirmation.review_sha256
            or authorization.generation != capability.confirmation.generation
            or authorization.actor_id != capability.confirmation.actor_id
            or capability.biometric_token not in self._biometrics
        ):
            raise LifecycleError("SIGNED_AUTHORIZATION_REQUIRED_OR_STALE")
        self._check_signature(signature, capability.confirmation)

    def is_current_authorization(
        self,
        capability: SignedAuthorization | None,
        signature: SignatureArtifact | None,
    ) -> bool:
        with self._lock:
            try:
                self._check_capability(capability, signature)
            except LifecycleError:
                return False
            return True

    def execute(
        self,
        capability: SignedAuthorization | None,
        signature: SignatureArtifact | None = None,
    ) -> SignedExecutionResult:
        with self._lock:
            self._check_capability(capability, signature)
            result = self._backend.execute(capability.authorization)
            return SignedExecutionResult(
                result=result,
                signature_verified=True,
                authorization_accepted=capability.authorization.status == "ACCEPTED",
            )
