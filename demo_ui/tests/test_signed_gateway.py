"""Security contract of the public, versioned demo gateway."""

from dataclasses import replace

import pytest

from dcta.lifecycle.errors import LifecycleError
from dcta.ponder.serialization import content_sha256

from demo_ui.crypto import DemoSigner
from demo_ui.orchestrator import DemoSession


PRIMARY = "Buy 5 DBS shares and send SGD 50 to Sarah from savings."


def ready_session():
    session = DemoSession()
    assert session.submit_text(PRIMARY).status == "READY_FOR_CONFIRMATION"
    assert session.confirm_transaction().confirmation_accepted
    return session


def signed_evidence(session):
    biometric = session.gateway.verify_biometric(session.confirmation)
    signature = session.signer.sign(
        content_sha256(session.state.review),
        content_sha256(session.confirmation),
        session.confirmation.actor_id,
    )
    return biometric, signature


def authorize(session, biometric, signature, *, actor_id=None, verification=None):
    return session.gateway.authorize(
        session.state.review,
        session.confirmation,
        biometric,
        signature,
        actor_id=actor_id or session.confirmation.actor_id,
        idempotency_key="signed-gateway-test",
        verification=verification,
    )


def verified_evidence(session):
    biometric, signature = signed_evidence(session)
    verification = session.gateway.verify_signature(
        session.state.review, session.confirmation, biometric, signature
    )
    return biometric, signature, verification


def assert_no_backend_authorization(session):
    assert not any(
        event.event == "AUTHORIZATION_ACCEPTED" for event in session.gateway.audit.records
    )


def test_unsigned_authorize_rejected_before_backend_call():
    session = ready_session()
    biometric, _ = signed_evidence(session)

    with pytest.raises(LifecycleError):
        authorize(session, biometric, None)

    assert_no_backend_authorization(session)


def test_valid_signature_without_prior_verification_proof_is_rejected():
    session = ready_session()
    biometric, signature = signed_evidence(session)

    with pytest.raises(LifecycleError, match="VERIFIED_SIGNATURE_REQUIRED"):
        authorize(session, biometric, signature)

    assert_no_backend_authorization(session)


def test_missing_biometric_rejected_before_backend_call():
    session = ready_session()
    _, signature = signed_evidence(session)

    with pytest.raises(LifecycleError):
        authorize(session, None, signature)

    assert_no_backend_authorization(session)


@pytest.mark.parametrize(
    "tamper",
    [
        lambda sig: replace(sig, signature="0" * 128),
        lambda sig: replace(sig, bundle_hash="0" * 64),
        lambda sig: replace(sig, confirmation_hash="0" * 64),
        lambda sig: replace(sig, actor_id="another-actor"),
        lambda sig: replace(sig, nonce="0" * 32),
    ],
    ids=["malformed_signature", "wrong_bundle", "wrong_confirmation", "wrong_actor", "wrong_nonce"],
)
def test_tampered_binding_rejected_before_backend_call(tamper):
    session = ready_session()
    biometric, signature, verification = verified_evidence(session)

    with pytest.raises(LifecycleError):
        authorize(session, biometric, tamper(signature), verification=verification)

    assert_no_backend_authorization(session)


def test_wrong_public_key_rejected_before_backend_call():
    session = ready_session()
    biometric, _ = signed_evidence(session)
    other = DemoSigner()
    signature = other.sign(
        content_sha256(session.state.review),
        content_sha256(session.confirmation),
        session.confirmation.actor_id,
    )

    with pytest.raises(LifecycleError):
        authorize(session, biometric, signature)

    assert_no_backend_authorization(session)


def test_wrong_actor_argument_rejected_before_backend_call():
    session = ready_session()
    biometric, signature = signed_evidence(session)

    with pytest.raises(LifecycleError):
        authorize(session, biometric, signature, actor_id="another-actor")

    assert_no_backend_authorization(session)


def test_stale_confirmation_rejected_before_backend_call():
    session = ready_session()
    biometric, signature = signed_evidence(session)
    session.gateway.invalidate()

    with pytest.raises(LifecycleError):
        authorize(session, biometric, signature)

    assert_no_backend_authorization(session)


def test_valid_signature_creates_signed_authorization():
    session = ready_session()
    biometric, signature, verification = verified_evidence(session)

    capability = authorize(session, biometric, signature, verification=verification)

    assert capability.authorization.status == "ACCEPTED"
    assert capability.schema_version == "signed-demo-authorization-v1"
    assert any(e.event == "AUTHORIZATION_ACCEPTED" for e in session.gateway.audit.records)


def test_execute_rejects_backend_authorization_without_signed_capability():
    session = ready_session()
    biometric, signature, verification = verified_evidence(session)
    capability = authorize(session, biometric, signature, verification=verification)
    before = session.gateway.bank.revision

    with pytest.raises(LifecycleError):
        session.gateway.execute(capability.authorization, signature)

    assert session.gateway.bank.revision == before


def test_execute_rejects_missing_or_tampered_signature():
    session = ready_session()
    biometric, signature, verification = verified_evidence(session)
    capability = authorize(session, biometric, signature, verification=verification)
    before = session.gateway.bank.revision

    with pytest.raises(LifecycleError):
        session.gateway.execute(capability, None)
    with pytest.raises(LifecycleError):
        session.gateway.execute(capability, replace(signature, signature="0" * 128))

    assert session.gateway.bank.revision == before


def test_execute_rejects_stale_signature_and_version():
    session = ready_session()
    biometric, signature, verification = verified_evidence(session)
    capability = authorize(session, biometric, signature, verification=verification)
    session.gateway.invalidate()
    before = session.gateway.bank.revision

    with pytest.raises(LifecycleError):
        session.gateway.execute(capability, signature)

    assert session.gateway.bank.revision == before


def test_valid_signed_execution_and_duplicate_are_idempotent():
    session = ready_session()
    biometric, signature, verification = verified_evidence(session)
    capability = authorize(session, biometric, signature, verification=verification)

    first = session.gateway.execute(capability, signature)
    second = session.gateway.execute(capability, signature)

    assert first.result.status == "SUCCEEDED"
    assert second.result.status == "ALREADY_EXECUTED"
    assert first.signature_verified and second.signature_verified
    assert session.gateway.bank.revision == 1
    assert len(session.gateway.simulated_investments) == 1
    assert first.result.receipt == second.result.receipt


def test_reject_after_authorization_retires_saved_capability():
    session = ready_session()
    biometric, signature, verification = verified_evidence(session)
    capability = authorize(session, biometric, signature, verification=verification)
    old_generation = capability.authorization.generation

    session.gateway.reject(session.state.review, actor_id=session.confirmation.actor_id)

    assert session.gateway._backend._generation > old_generation
    with pytest.raises(LifecycleError):
        session.gateway.execute(capability, signature)
    assert session.gateway.bank.revision == 0


def test_v1_v2_v1_does_not_revive_signed_capability():
    session = ready_session()
    biometric, signature, verification = verified_evidence(session)
    capability = authorize(session, biometric, signature, verification=verification)

    session.submit_text(PRIMARY.replace("SGD 50", "SGD 60"))
    session.submit_text(PRIMARY)

    with pytest.raises(LifecycleError):
        session.gateway.execute(capability, signature)
    assert session.gateway.bank.revision == 0
