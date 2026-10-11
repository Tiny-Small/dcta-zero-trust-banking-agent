"""Tests for the demo scenarios — verifying each preset works as expected."""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
_src = _root / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

import pytest
from demo_ui.scenarios import SCENARIOS, get_scenario
from demo_ui.orchestrator import DemoSession
from demo_ui.scripted_provider import ScriptedWireControl
from dcta.mixed.gateway import MixedGateway
from dcta.mixed.session import MixedTextLifecycle
from dcta.business.mock import mock_bank, mock_policy
from dcta.mixed.business import mock_investment_state, mock_investment_policy


def session_for_scenario(scenario):
    provider = ScriptedWireControl(statuses=scenario.fault_statuses)
    gw = MixedGateway(
        mock_bank(), mock_policy(),
        mock_investment_state(), mock_investment_policy(),
    )
    lc = MixedTextLifecycle(provider, gw)
    return DemoSession(provider=provider, gateway=gw, lifecycle=lc)


def test_all_scenarios_defined():
    assert len(SCENARIOS) == 6
    keys = [s.key for s in SCENARIOS]
    assert keys == ["A", "B", "C", "D", "E", "F"]


def test_scenario_a_happy_path():
    scenario = get_scenario("A")
    s = session_for_scenario(scenario)
    view = s.submit_text(scenario.text)
    assert view.status == "READY_FOR_CONFIRMATION"
    # Full flow
    s.confirm_transaction()
    s.simulate_biometric()
    s.sign_and_authorize()
    view = s.execute()
    assert view.receipt.status == "SUCCEEDED"


def test_scenario_b_ambiguous_beneficiary():
    scenario = get_scenario("B")
    s = session_for_scenario(scenario)
    view = s.submit_text(scenario.text)
    assert view.status == "NEEDS_GROUNDING"
    assert view.clarification is not None
    assert len(view.clarification.options) == 2
    # Resolve
    ch = view.clarification
    view = s.resolve_grounding(ch.choice_id, ch.options[0].entity_id)
    assert view.status == "READY_FOR_CONFIRMATION"


def test_scenario_c_semantic_discrepancy():
    scenario = get_scenario("C")
    assert scenario.is_fault_injection
    s = session_for_scenario(scenario)
    view = s.submit_text(scenario.text)
    assert view.status == "SEMANTIC_FROZEN"
    assert not view.confirmation_available


def test_scenario_d_business_block():
    scenario = get_scenario("D")
    s = session_for_scenario(scenario)
    view = s.submit_text(scenario.text)
    assert view.status == "BLOCKED"
    assert not view.confirmation_available


def test_scenario_e_prompt_injection():
    scenario = get_scenario("E")
    s = session_for_scenario(scenario)
    view = s.submit_text(scenario.text)
    assert view.status == "UPSTREAM_STOP"
    assert view.reason == "PROMPT_INJECTION_SHIELD_BLOCKED"


def test_scenario_f_duplicate_execution():
    scenario = get_scenario("F")
    s = session_for_scenario(scenario)
    s.submit_text(scenario.text)
    s.confirm_transaction()
    s.simulate_biometric()
    s.sign_and_authorize()
    view1 = s.execute()
    assert view1.receipt.status == "SUCCEEDED"
    view2 = s.execute_again()
    assert view2.receipt.status == "ALREADY_EXECUTED"
