"""The three final LIVE request adapters preserve bounded model controls."""

import pytest

from dcta.action_transport.provider import ActionTargetTransport, VERSION as ACTION_VERSION
from dcta.extraction_transport.provider import RoleTargetTransport, VERSION as ROLE_VERSION
from dcta.semantic_transport.provider import SemanticApplicabilityTransport, VERSION as SEMANTIC_VERSION
from demo_ui.orchestrator import DemoSession
from demo_ui.scenarios import get_scenario
from demo_ui.scripted_provider import ScriptedWireControl


def test_final_live_transport_chain_uses_versioned_target_requests():
    wire = ScriptedWireControl()
    provider = SemanticApplicabilityTransport(ActionTargetTransport(RoleTargetTransport(wire)))
    session = DemoSession(provider=provider)
    assert session.submit_text(get_scenario("A").text).status == "READY_FOR_CONFIRMATION"

    requests = wire.requests
    role = next(r for r in requests if r["state"]["trusted_controls"]["stage"] == "role")
    relation = next(r for r in requests if r["state"]["trusted_controls"]["stage"] == "mixed_relation")
    semantic = next(r for r in requests if r["state"]["trusted_controls"]["stage"] == "mixed_semantic")

    assert role["state"]["trusted_controls"]["extension"] == ROLE_VERSION
    assert all(f"Target candidate ID: {key}." in q["instructions"] for key, q in role["questions"].items())
    assert relation["state"]["trusted_controls"]["action_extension"] == ACTION_VERSION
    assert semantic["state"]["trusted_controls"]["semantic_extension"] == SEMANTIC_VERSION
    assert all(q["type"] == "choice" for r in (role, relation, semantic) for q in r["questions"].values())


def test_live_construction_requires_environment_or_explicit_settings(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("JEV_MODEL", raising=False)
    with pytest.raises(ValueError, match="credential or model unavailable"):
        DemoSession.live()
