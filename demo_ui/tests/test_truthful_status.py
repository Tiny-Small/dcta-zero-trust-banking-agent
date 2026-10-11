"""The demo must display the backend's actual stop reason."""

from demo_ui.app import render_lifecycle, render_operation_cards, render_receipt
from demo_ui.orchestrator import DemoSession
from demo_ui.scenarios import get_scenario
from demo_ui.scripted_provider import ScriptedWireControl
from demo_ui.view_models import build_lifecycle_steps


def _step(view, label):
    return next(step for step in view.lifecycle_steps if step.label == label)


def test_unresolved_is_not_displayed_as_discrepancy():
    session = DemoSession()
    view = session.submit_text(
        "Buy 5 UOB shares and transfer 10 SGD to Sarah from savings"
    )

    assert view.status == "SEMANTIC_FROZEN"
    assert session.state.semantic_decision.result == "UNRESOLVED"
    assert "asset" in _step(view, "Grounding").detail.lower()
    assert "Grounding resolved" not in _step(view, "Grounding").detail
    assert "UNRESOLVED" in _step(view, "Semantic validation").detail
    assert "synthetic investment catalog" in _step(view, "Semantic validation").detail
    assert "DISCREPANCY" not in render_lifecycle(view)
    assert "stopped before interpretation" not in render_operation_cards(view)
    assert not view.confirmation_available


def test_real_semantic_discrepancy_keeps_its_label():
    session = DemoSession(
        provider=ScriptedWireControl(statuses={"global:joint_bindings": "DISCREPANCY"})
    )
    view = session.submit_text(
        "Buy 5 DBS shares and send SGD 50 to Sarah from savings."
    )

    assert session.state.semantic_decision.result == "DISCREPANCY"
    assert "DISCREPANCY" in _step(view, "Semantic validation").detail


class _RecognizeUobRole(ScriptedWireControl):
    """Let the normal mock directory decide whether a recognized asset exists."""

    def decide(self, *, state, questions):
        response = super().decide(state=state, questions=questions)
        if state["trusted_controls"]["stage"] == "role":
            for candidate in state["untrusted_data"]["state"]["candidate_inventory"]:
                if candidate["text"] == "UOB":
                    response["raw_response"]["answers"][candidate["candidate_id"]][
                        "choice"
                    ] = "asset"
        return response


def test_unsupported_asset_is_a_mock_catalog_limit_not_a_discrepancy():
    session = DemoSession(provider=_RecognizeUobRole())
    view = session.submit_text(
        "Buy 5 UOB shares and send SGD 10 to Sarah from savings"
    )

    asset = next(field for field in session.state.grounding.fields if field.field == "ASSET")
    assert asset.status == "NOT_FOUND"
    assert asset.selected_entity_id is None
    assert session.state.semantic_decision.result == "UNRESOLVED"
    assert "synthetic investment catalog" in _step(view, "Grounding").detail
    assert "DISCREPANCY" not in render_lifecycle(view)
    assert not view.confirmation_available


def test_contract_error_is_not_displayed_as_semantic_discrepancy():
    session = DemoSession(
        provider=ScriptedWireControl(statuses={"global:joint_bindings": "DISCREPANCY"})
    )
    session.submit_text(get_scenario("C").text)
    state = session.state
    decision = type(state.semantic_decision).model_validate({
        **state.semantic_decision.model_dump(mode="python"),
        "result": "CONTRACT_ERROR",
    })
    presentation_state = type(state).model_validate({
        **state.model_dump(mode="python"),
        "semantic_decision": decision,
    })

    step = next(
        step for step in build_lifecycle_steps(presentation_state)
        if step.label == "Semantic validation"
    )
    assert "CONTRACT_ERROR" in step.detail
    assert "DISCREPANCY" not in step.detail


def test_other_lifecycle_and_receipt_labels_remain_distinct():
    happy = DemoSession()
    ready = happy.submit_text(get_scenario("A").text)
    assert ready.status == "READY_FOR_CONFIRMATION"
    assert "MATCH" in _step(ready, "Semantic validation").detail
    assert "PASS" in _step(ready, "Business/risk validation").detail

    ambiguous = DemoSession().submit_text(get_scenario("B").text)
    assert ambiguous.status == "NEEDS_GROUNDING"
    assert "Ambiguous" in _step(ambiguous, "Grounding").detail

    blocked = DemoSession().submit_text(get_scenario("D").text)
    assert blocked.status == "BLOCKED"
    assert "BLOCKED" in _step(blocked, "Business/risk validation").detail
    assert "DISCREPANCY" not in render_lifecycle(blocked)

    shielded = DemoSession().submit_text(get_scenario("E").text)
    assert shielded.status == "UPSTREAM_STOP"
    assert "Prompt injection blocked" in _step(shielded, "Input shield").detail
    assert "DISCREPANCY" not in render_lifecycle(shielded)

    happy.confirm_transaction()
    happy.simulate_biometric()
    happy.sign_and_authorize()
    executed = happy.execute()
    assert executed.receipt.status == "SUCCEEDED"
    assert "Completed" in render_receipt(executed)
    duplicate = happy.execute_again()
    assert duplicate.receipt.status == "ALREADY_EXECUTED"
    assert "ALREADY_EXECUTED" in render_receipt(duplicate)
