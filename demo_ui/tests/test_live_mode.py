"""Live demo setup preserves the proven model-facing request contracts."""

import os

from dcta.ponder_mvp import demo as ponder_demo
from dcta.ponder_mvp._extractor.providers import decisions
import dcta

from demo_ui import orchestrator
from demo_ui.orchestrator import DemoSession
from demo_ui.scripted_provider import ScriptedWireControl


class TargetSensitiveProvider(ScriptedWireControl):
    """Model double reproducing uniform roles when target selectors are absent."""

    def decide(self, *, state, questions):
        response = super().decide(state=state, questions=questions)
        if state["trusted_controls"]["stage"] == "role" and any(
            f"Target candidate ID: {key}." not in question["instructions"]
            for key, question in questions.items()
        ):
            for answer in response["raw_response"]["answers"].values():
                answer["choice"] = "asset_quantity"
        return response


def test_live_session_uses_targeted_requests_for_mixed_command(monkeypatch, tmp_path):
    provider = TargetSensitiveProvider()
    monkeypatch.setattr(decisions, "read_settings", lambda path: ("test-key", provider.model))
    monkeypatch.setattr(decisions, "DecisionsProvider", lambda key, model: provider)
    guarded = ponder_demo.GuardedProvider

    def temp_guard(inner, **kwargs):
        assert kwargs["journal"] == os.devnull
        assert str(dcta.__file__) in kwargs["hashes"]
        kwargs["journal"] = tmp_path / "requests.jsonl"
        return guarded(inner, **kwargs)

    monkeypatch.setattr(ponder_demo, "GuardedProvider", temp_guard)
    monkeypatch.setattr(orchestrator, "__file__", str(tmp_path / "installed/demo_ui/orchestrator.py"))
    session = DemoSession.live(str(tmp_path / "settings"))

    view = session.submit_text("Buy 5 DBS shares and send SGD 50 to Sarah from savings.")

    assert view.status == "READY_FOR_CONFIRMATION"
    requests = provider.requests
    role = next(r for r in requests if r["state"]["trusted_controls"]["stage"] == "role")
    assert all(
        f"Target candidate ID: {key}." in question["instructions"]
        for key, question in role["questions"].items()
    )
    relation = next(r for r in requests if r["state"]["trusted_controls"]["stage"] == "mixed_relation")
    semantic = next(r for r in requests if r["state"]["trusted_controls"]["stage"] == "mixed_semantic")
    assert relation["state"]["trusted_controls"]["action_extension"] == "investment-action-shield-transport-v2"
    assert semantic["state"]["trusted_controls"]["semantic_extension"] == "mixed-semantic-applicability-transport-v2"
