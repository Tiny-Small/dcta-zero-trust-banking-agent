"""Demo session orchestrator — thin adapter around the frozen mixed lifecycle.

This class manages the stateful demo flow:
  text -> grounding -> confirmation -> biometric -> signing -> execution

It NEVER bypasses backend gates.  Each method calls the corresponding backend
interface and surfaces the result.  If the backend returns FROZEN, BLOCKED, or
UPSTREAM_STOP, the orchestrator reflects that state and does not allow
subsequent steps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from uuid import uuid4
from typing import Any

from dcta.ponder.serialization import content_sha256
from dcta.lifecycle.errors import LifecycleError
from dcta.business.mock import mock_bank, mock_policy
from dcta.mixed.business import mock_investment_state, mock_investment_policy
from dcta.mixed.gateway import MixedGateway, MixedExecutionResult
from dcta.mixed.session import MixedTextLifecycle, MixedLifecycleState
from dcta.mixed.records import MixedInterpretation

from .crypto import DemoSigner, SignatureArtifact
from .signed_gateway import (
    BiometricProof,
    SignedAuthorization,
    SignedExecutionGateway,
    SignedExecutionResult,
    VerifiedSignature,
)
from .view_models import (
    DemoStateView,
    OperationCard,
    build_operation_cards,
    build_lifecycle_steps,
    build_audit_timeline,
    build_receipt_view,
    build_clarification_view,
    STOPPED_STATUSES,
    stop_reason,
)
from .scripted_provider import ScriptedWireControl


# --------------------------------------------------------------------------- #
#  Demo phase tracking
# --------------------------------------------------------------------------- #

@dataclass
class DemoPhase:
    """Tracks which demo phases have been completed."""
    text_submitted: bool = False
    grounding_resolved: bool = False
    confirmed: bool = False
    biometric_completed: bool = False
    signed: bool = False
    executed: bool = False


# --------------------------------------------------------------------------- #
#  Demo session
# --------------------------------------------------------------------------- #


class DemoSession:
    """Stateful demo adapter around the frozen mixed lifecycle.

    The orchestrator enforces ordering:
      1. submit_text / resolve_grounding
      2. confirm_transaction (requires READY_FOR_CONFIRMATION)
      3. simulate_biometric (requires accepted confirmation)
      4. sign_and_authorize (requires biometric completed)
      5. execute (requires valid signature + accepted authorization)

    Each step is a separate user action — nothing happens automatically.
    """

    def __init__(self, provider=None, gateway=None, lifecycle=None):
        """Create a new demo session.

        If no provider/gateway/lifecycle is supplied, a fresh scripted
        demo-mode session is created (no live API key needed).
        """
        if provider is None:
            provider = ScriptedWireControl()

        if gateway is None:
            gateway = MixedGateway(
                mock_bank(),
                mock_policy(),
                mock_investment_state(),
                mock_investment_policy(),
            )

        if lifecycle is None:
            lifecycle = MixedTextLifecycle(provider, gateway)
        elif lifecycle.gateway is not gateway:
            raise ValueError("Demo lifecycle and gateway must share one backend")

        self.provider = provider
        self.signer = DemoSigner()
        self.gateway = SignedExecutionGateway(gateway, self.signer.public_key_hex)
        self._lifecycle = lifecycle

        # Current backend lifecycle state.
        self.state: MixedLifecycleState | None = None

        # Backend artifacts.
        self.confirmation = None  # Confirmation
        self.authorization = None  # Authorization
        self.execution_result: MixedExecutionResult | None = None
        self.signed_authorization: SignedAuthorization | None = None
        self.signed_execution_result: SignedExecutionResult | None = None

        # Demo-only artifacts (not part of the backend).
        self.signature_artifact: SignatureArtifact | None = None
        self.signature_proof: VerifiedSignature | None = None
        self.biometric_proof: BiometricProof | None = None
        self.biometric_verified = False
        self.phase = DemoPhase()

    # ------------------------------------------------------------------ #
    #  Step 1: Submit text
    # ------------------------------------------------------------------ #
    def submit_text(self, text: str) -> DemoStateView:
        """Submit user text to the full shielded mixed lifecycle."""
        self._reset_downstream()
        self.state = self._lifecycle.submit_text(text, source_id="demo:input")
        self.phase.text_submitted = True
        return self._build_view()

    # ------------------------------------------------------------------ #
    #  Step 1b: Resolve grounding ambiguity
    # ------------------------------------------------------------------ #
    def resolve_grounding(self, choice_id: str, entity_id: str) -> DemoStateView:
        """Resolve an ambiguous entity via the versioned clarification path."""
        if self.state is None:
            return self._error_view("No active transaction to clarify.")
        if self.state.status != "NEEDS_GROUNDING":
            return self._error_view(
                f"Transaction is not awaiting clarification (status: {self.state.status})."
            )
        self.state = self._lifecycle.answer_grounding(
            self.state, choice_id, entity_id
        )
        self.phase.grounding_resolved = True
        return self._build_view()

    # ------------------------------------------------------------------ #
    #  Step 2: Confirm the exact bundle
    # ------------------------------------------------------------------ #
    def confirm_transaction(self) -> DemoStateView:
        """User confirms the exact validated transaction bundle.

        Requires READY_FOR_CONFIRMATION from the backend.
        Confirmation is NOT authorization.
        """
        if self.state is None or self.state.status != "READY_FOR_CONFIRMATION":
            if self.state is not None and self.state.status in STOPPED_STATUSES:
                return self._error_view(
                    "Cannot confirm: " + stop_reason(self.state.status, self.state.reason)
                )
            return self._error_view(
                "Transaction is not eligible for confirmation. "
                "The bundle must pass all gates first."
            )
        if self.state.review is None:
            return self._error_view("No review available to confirm.")
        if self.confirmation is not None:
            return self._error_view("This review already has a confirmation decision.")

        review = self.state.review
        actor = self.gateway.bank.authenticated_user_id
        self.confirmation = self.gateway.confirm(
            review, accepted=True, actor_id=actor
        )
        self.phase.confirmed = True
        return self._build_view()

    def reject_transaction(self) -> DemoStateView:
        """User rejects the exact bundle — no confirmation, no authorization."""
        if self.state is None or self.state.status != "READY_FOR_CONFIRMATION":
            return self._error_view("Transaction is not eligible for rejection.")
        if self.state.review is None:
            return self._error_view("No review available to reject.")
        actor = self.gateway.bank.authenticated_user_id
        try:
            self.confirmation = self.gateway.reject(
                self.state.review, actor_id=actor
            )
        except LifecycleError as error:
            return self._error_view(f"Cannot reject: {error}")
        self.authorization = None
        self.signed_authorization = None
        self.signed_execution_result = None
        self.execution_result = None
        self.biometric_proof = None
        self.biometric_verified = False
        self.signature_artifact = None
        self.signature_proof = None
        self.phase = DemoPhase(text_submitted=True)
        return self._build_view()

    # ------------------------------------------------------------------ #
    #  Step 3: Simulated biometric verification
    # ------------------------------------------------------------------ #
    def simulate_biometric(self) -> DemoStateView:
        """Simulated biometric verification (NOT real FaceID/TouchID).

        Requires an accepted confirmation.  This step is explicit —
        confirmation does NOT automatically authorize.
        """
        if self.confirmation is None or self.confirmation.status != "ACCEPTED":
            return self._error_view(
                "Cannot verify biometrics: transaction must be confirmed first."
            )
        try:
            self.biometric_proof = self.gateway.verify_biometric(self.confirmation)
        except LifecycleError as error:
            return self._error_view(f"Cannot verify biometrics: {error}")
        self.biometric_verified = True
        self.phase.biometric_completed = True
        return self._build_view()

    # ------------------------------------------------------------------ #
    #  Step 4: Cryptographic sign-off + authorization
    # ------------------------------------------------------------------ #
    def sign_transaction(self) -> DemoStateView:
        """Sign the current confirmation, then verify at the signed gateway."""
        if not self.gateway.is_current_confirmation(self.confirmation):
            return self._error_view("Cannot sign: current confirmation required.")
        if not self.gateway.is_current_biometric(
            self.biometric_proof, self.confirmation
        ):
            return self._error_view("Cannot sign: simulated biometric verification required first.")
        if self.signed_authorization is not None:
            return self._error_view("This transaction is already authorized.")
        review_hash = self.confirmation.review_sha256
        confirmation_hash = content_sha256(self.confirmation)
        actor = self.confirmation.actor_id
        self.signature_artifact = self.signer.sign(
            bundle_hash=review_hash,
            confirmation_hash=confirmation_hash,
            actor_id=actor,
        )
        try:
            self.signature_proof = self.gateway.verify_signature(
                self.state.review if self.state else None,
                self.confirmation,
                self.biometric_proof,
                self.signature_artifact,
            )
        except LifecycleError as error:
            self.signature_artifact = None
            self.signature_proof = None
            return self._error_view(f"Signature verification failed: {error}.")
        self.phase.signed = True
        return self._build_view()

    def authorize_signed(self) -> DemoStateView:
        """Create backend authorization only through the signed boundary."""
        if not self.gateway.is_current_signature(
            self.signature_proof,
            self.confirmation,
            self.biometric_proof,
            self.signature_artifact,
        ):
            return self._error_view("Cannot authorize: verified current signature required.")
        if self.signed_authorization is not None:
            return self._error_view("This transaction is already authorized.")
        try:
            self.signed_authorization = self.gateway.authorize(
                self.state.review if self.state else None,
                self.confirmation,
                self.biometric_proof,
                self.signature_artifact,
                actor_id=self.confirmation.actor_id,
                idempotency_key="demo:" + uuid4().hex,
                verification=self.signature_proof,
            )
        except LifecycleError as error:
            return self._error_view(f"Signed authorization refused: {error}.")
        self.authorization = self.signed_authorization.authorization
        return self._build_view()

    def sign_and_authorize(self) -> DemoStateView:
        """Compatibility helper for scripted tests; the UI uses two clicks."""
        signed = self.sign_transaction()
        if signed.error is not None:
            return signed
        return self.authorize_signed()

    # ------------------------------------------------------------------ #
    #  Step 5: Execute via the zero-trust gateway
    # ------------------------------------------------------------------ #
    def execute(self) -> DemoStateView:
        """Execute the authorized transaction via the mock gateway.

        Requires:
          - Accepted authorization
          - Verified signature

        The gateway verifies the authorization is current, not stale,
        and not already executed (idempotent).
        """
        if self.signed_authorization is None:
            return self._error_view(
                "Cannot execute: transaction must be authorized first."
            )
        if self.signature_artifact is None:
            return self._error_view(
                "Cannot execute: cryptographic signature required."
            )

        try:
            signed_result = self.gateway.execute(
                self.signed_authorization, self.signature_artifact
            )
            self.signed_execution_result = signed_result
            self.execution_result = signed_result.result
            self.phase.executed = signed_result.result.status in {
                "SUCCEEDED", "ALREADY_EXECUTED"
            }
        except LifecycleError as e:
            return self._error_view(f"Execution blocked: {e}")
        return self._build_view()

    # ------------------------------------------------------------------ #
    #  Utility: duplicate execution for demo scenario F
    # ------------------------------------------------------------------ #
    def execute_again(self) -> DemoStateView:
        """Attempt to execute the same authorization a second time.

        The backend gateway returns ALREADY_EXECUTED — no second debit.
        """
        if self.execution_result is None or self.execution_result.status not in {
            "SUCCEEDED", "ALREADY_EXECUTED"
        }:
            return self._error_view("Execute the signed transaction first.")
        return self.execute()

    # ------------------------------------------------------------------ #
    #  View construction
    # ------------------------------------------------------------------ #
    def _build_view(self) -> DemoStateView:
        state = self.state

        confirmation_accepted = self.gateway.is_current_confirmation(
            self.confirmation
        )
        biometric_completed = self.gateway.is_current_biometric(
            self.biometric_proof, self.confirmation
        )
        signature_verified = self.gateway.is_current_signature(
            self.signature_proof,
            self.confirmation,
            self.biometric_proof,
            self.signature_artifact,
        )
        authorization_accepted = self.gateway.is_current_authorization(
            self.signed_authorization, self.signature_artifact
        )
        signing_available = (
            confirmation_accepted
            and biometric_completed
            and self.signed_authorization is None
        )

        if state is None:
            return DemoStateView(
                status="INIT",
                reason="",
                operation_cards=[],
                lifecycle_steps=[],
                clarification=None,
                confirmation_available=False,
                confirmation_accepted=confirmation_accepted,
                authorization_available=False,
                authorization_accepted=authorization_accepted,
                execution_available=False,
                biometric_completed=biometric_completed,
                signature_verified=signature_verified,
                receipt=None,
                audit_entries=[],
                audit_verified=self.gateway.audit.verify(),
                error=None,
                signing_available=signing_available,
            )

        cards = build_operation_cards(state)
        steps = build_lifecycle_steps(
            state,
            confirmation_accepted=confirmation_accepted,
            authorization_accepted=authorization_accepted,
            biometric_completed=biometric_completed,
            signature_verified=signature_verified,
            executed=(
                self.signed_execution_result is not None
                and self.signed_execution_result.result.status
                in {"SUCCEEDED", "ALREADY_EXECUTED"}
            ),
        )
        clarification = build_clarification_view(state)

        # Determine availability based on backend state + demo phase.
        confirmation_available = (
            state.status == "READY_FOR_CONFIRMATION"
            and state.review is not None
            and self.confirmation is None
        )
        authorization_available = (
            signature_verified
            and self.authorization is None
        )
        execution_available = (
            authorization_accepted
            and self.signed_execution_result is None
        )

        receipt_view = None
        if self.signed_execution_result is not None:
            receipt_view = build_receipt_view(self.signed_execution_result)

        audit_entries = build_audit_timeline(self.gateway.audit.records)

        return DemoStateView(
            status=state.status,
            reason=state.reason,
            operation_cards=cards,
            lifecycle_steps=steps,
            clarification=clarification,
            confirmation_available=confirmation_available,
            confirmation_accepted=confirmation_accepted,
            authorization_available=authorization_available,
            authorization_accepted=authorization_accepted,
            execution_available=execution_available,
            biometric_completed=biometric_completed,
            signature_verified=signature_verified,
            receipt=receipt_view,
            audit_entries=audit_entries,
            audit_verified=self.gateway.audit.verify(),
            error=None,
            signing_available=signing_available,
        )

    def _error_view(self, msg: str) -> DemoStateView:
        base = self._build_view()
        return DemoStateView(
            status=base.status,
            reason=base.reason,
            operation_cards=base.operation_cards,
            lifecycle_steps=base.lifecycle_steps,
            clarification=base.clarification,
            confirmation_available=base.confirmation_available,
            confirmation_accepted=base.confirmation_accepted,
            authorization_available=base.authorization_available,
            authorization_accepted=base.authorization_accepted,
            execution_available=base.execution_available,
            biometric_completed=base.biometric_completed,
            signature_verified=base.signature_verified,
            receipt=base.receipt,
            audit_entries=base.audit_entries,
            audit_verified=base.audit_verified,
            error=msg,
            signing_available=base.signing_available,
        )

    def _reset_downstream(self):
        """Reset downstream artifacts when a new text is submitted."""
        self.gateway.invalidate()
        self.confirmation = None
        self.authorization = None
        self.execution_result = None
        self.signed_authorization = None
        self.signed_execution_result = None
        self.signature_artifact = None
        self.signature_proof = None
        self.biometric_proof = None
        self.biometric_verified = False
        self.phase = DemoPhase()

    # ------------------------------------------------------------------ #
    #  Factory: live API mode
    # ------------------------------------------------------------------ #
    @classmethod
    def live(cls, settings_path: str | None = None) -> "DemoSession":
        """Create a session using the live OpenRouter Jev API."""
        from dcta.ponder_mvp._extractor.providers.decisions import (
            DecisionsProvider,
            read_settings,
        )
        from dcta.ponder_mvp.demo import GuardedProvider
        from dcta.extraction_transport.provider import RoleTargetTransport
        from dcta.action_transport.provider import ActionTargetTransport
        from dcta.semantic_transport.provider import SemanticApplicabilityTransport
        from pathlib import Path
        import hashlib
        import os
        import dcta

        key, model = read_settings(Path(settings_path) if settings_path is not None else Path(os.devnull))
        if model != "typesafe/jev-1.13":
            raise ValueError("Pinned model required: typesafe/jev-1.13")
        backend_package = Path(dcta.__file__).resolve().parent
        hashes = {
            str(f): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in backend_package.rglob("*.py")
        }
        guarded = GuardedProvider(
            DecisionsProvider(key, model=model),
            max_requests=80,
            max_questions=2000,
            cost_stop=1,
            hashes=hashes,
            journal=os.devnull,
        )
        provider = SemanticApplicabilityTransport(
            ActionTargetTransport(RoleTargetTransport(guarded))
        )
        return cls(provider=provider)
