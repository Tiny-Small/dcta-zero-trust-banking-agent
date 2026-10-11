"""The demo explains remaining business questions after entity selection."""

from demo_ui.app import create_app, render_full
from demo_ui.orchestrator import DemoSession


def test_missing_currency_after_john_selection_shows_next_action():
    session = DemoSession()
    view = session.submit_text("Buy 5 DBS shares and send 50 to John from savings")
    view = session.resolve_grounding(
        view.clarification.choice_id, view.clarification.options[0].entity_id
    )

    assert view.status == "NEEDS_CLARIFICATION"
    detail = view.lifecycle_steps[4].detail
    assert "Which currency did you mean?" in detail
    assert "Submit" in detail
    assert "Which currency did you mean?" in render_full(view)
    assert all(step.status == "blocked" for step in view.lifecycle_steps[5:])


def test_editing_text_requires_submit_before_selecting_john():
    app = create_app()
    callbacks = {event.fn.__name__: event.fn for event in app.fns.values()}
    original = "Buy 5 DBS shares and send 50 to John from savings"
    revised = "Buy 5 DBS shares and send 50 USD to John from savings"
    callbacks["do_submit"](original)

    html, _, _ = callbacks["clarify_first"](revised)

    assert "Click Submit" in html
    assert "Clarification Required" in html
    assert "Review Transaction" not in html
