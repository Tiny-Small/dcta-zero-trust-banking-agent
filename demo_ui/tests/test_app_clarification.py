"""Exercise the clarification callbacks registered on the Gradio app."""

import pytest

from demo_ui.app import create_app


@pytest.mark.parametrize(
    ("callback_name", "selected_name"),
    [("clarify_first", "John Lim"), ("clarify_second", "John Tan")],
)
def test_ambiguous_beneficiary_button_resolves_selected_person(callback_name, selected_name):
    app = create_app()
    callbacks = {event.fn.__name__: event.fn for event in app.fns.values()}

    scenario_html, _, first_label, second_label = callbacks["do_scenario"](
        "B. Ambiguous beneficiary"
    )
    assert "Clarification Required" in scenario_html
    assert (first_label, second_label) == ("Select: John Lim", "Select: John Tan")

    resolved_html, _, _ = callbacks[callback_name]()

    assert "Review Transaction" in resolved_html
    assert "Clarification Required" not in resolved_html
    assert selected_name in resolved_html
