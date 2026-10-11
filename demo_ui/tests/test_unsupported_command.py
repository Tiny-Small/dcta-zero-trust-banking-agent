"""The demo should explain stopped commands instead of showing progress."""

from demo_ui.app import render_full
from demo_ui.orchestrator import DemoSession


def test_investment_only_command_explains_why_it_stopped():
    session = DemoSession()

    view = session.submit_text("Buy and sell 5 DBS shares")

    assert view.status == "UNSUPPORTED"
    assert view.lifecycle_steps[1].status == "fail"
    assert "one investment and one money transfer or payment" in view.lifecycle_steps[1].detail
    assert all(step.status == "blocked" for step in view.lifecycle_steps[2:])
    html = render_full(view)
    assert "one investment and one money transfer or payment" in html
    assert "Awaiting interpretation" not in html

    confirmation = session.confirm_transaction()
    assert "one investment and one money transfer or payment" in confirmation.error
    assert not confirmation.confirmation_available
