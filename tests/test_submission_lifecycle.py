"""Standalone synthetic checks of the submission's backend contract."""

from dcta.business.mock import mock_bank, mock_policy
from dcta.mixed.business import mock_investment_policy, mock_investment_state
from dcta.mixed.gateway import MixedGateway
from dcta.mixed.session import MixedTextLifecycle
from demo_ui.orchestrator import DemoSession
from demo_ui.scenarios import get_scenario
from demo_ui.scripted_provider import ScriptedWireControl


def _session(*, statuses=None, daily_count_limit=None):
    provider = ScriptedWireControl(statuses=statuses)
    policy = mock_policy()
    if daily_count_limit is not None:
        policy = type(policy).model_validate({
            **policy.model_dump(mode="python"),
            "daily_transaction_count_limit": daily_count_limit,
        })
    gateway = MixedGateway(mock_bank(), policy, mock_investment_state(), mock_investment_policy())
    lifecycle = MixedTextLifecycle(provider, gateway)
    return DemoSession(provider=provider, gateway=gateway, lifecycle=lifecycle)


def _execute(session):
    assert session.confirm_transaction().confirmation_accepted
    assert session.simulate_biometric().biometric_completed
    assert session.sign_transaction().signature_verified
    assert session.authorize_signed().authorization_accepted
    return session.execute()


def test_shield_stops_injection_before_any_model_question():
    session = _session()
    view = session.submit_text(get_scenario("E").text)
    assert view.status == "UPSTREAM_STOP"
    assert session.provider.requests == []
    assert session.gateway.bank.revision == 0


def test_quoted_reference_command_never_becomes_an_executable_operation():
    session = _session()
    view = session.submit_text("Use 'send SGD 50 to Sarah from savings' as reference.")
    assert view.status != "READY_FOR_CONFIRMATION"
    assert view.operation_cards == []
    assert session.gateway.bank.revision == 0


def test_mixed_operations_are_separate_and_duplicate_execution_is_atomic():
    session = _session()
    view = session.submit_text(get_scenario("A").text)
    assert view.status == "READY_FOR_CONFIRMATION"
    assert {card.goal for card in view.operation_cards} == {"Investment", "Transfer"}
    first = _execute(session)
    assert first.receipt.status == "SUCCEEDED"
    second = session.execute_again()
    assert second.receipt.status == "ALREADY_EXECUTED"
    assert session.gateway.bank.revision == 1
    assert len(session.gateway.simulated_investments) == 1
    assert session.gateway.receipts[0] == session.execution_result.receipt


def test_ambiguity_requires_explicit_new_grounding_revision():
    session = _session()
    view = session.submit_text(get_scenario("B").text)
    assert view.status == "NEEDS_GROUNDING"
    choice = session.state.grounding.clarifications[0]
    previous = session.state.grounding.revision
    view = session.resolve_grounding(choice.id, choice.options[0].id)
    assert view.status == "READY_FOR_CONFIRMATION"
    assert session.state.grounding.revision == previous + 1
    assert session.state.grounding_parents


def test_semantic_discrepancy_and_business_limit_block_confirmation():
    frozen = _session(statuses={"global:joint_bindings": "DISCREPANCY"})
    assert frozen.submit_text(get_scenario("A").text).status == "SEMANTIC_FROZEN"
    assert not frozen.confirm_transaction().confirmation_accepted
    blocked = _session()
    assert blocked.submit_text(get_scenario("D").text).status == "BLOCKED"
    assert not blocked.confirm_transaction().confirmation_accepted


def test_daily_operation_limit_blocks_a_second_mixed_bundle():
    session = _session(daily_count_limit=2)
    assert session.submit_text(get_scenario("A").text).status == "READY_FOR_CONFIRMATION"
    assert _execute(session).receipt.status == "SUCCEEDED"
    second = session.submit_text(get_scenario("A").text)
    assert second.status == "BLOCKED"
    assert session.gateway.bank.revision == 1
