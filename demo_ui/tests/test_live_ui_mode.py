"""The UI keeps its selected provider mode across user actions."""

from demo_ui.app import SessionContainer, create_app
from demo_ui.orchestrator import DemoSession


def test_live_session_reset_recreates_live_provider(monkeypatch):
    paths = []

    def fake_live(cls, path):
        paths.append(path)
        return cls()

    monkeypatch.setattr(DemoSession, "live", classmethod(fake_live))
    container = SessionContainer(live_mode=True)
    first = container.get()

    container.reset()

    assert paths == [None, None]
    assert container.get() is not first


def test_live_ui_keeps_live_provider_when_resetting_or_loading_scenario(monkeypatch):
    paths = []

    def fake_live(cls, path):
        paths.append(path)
        return cls()

    monkeypatch.setattr(DemoSession, "live", classmethod(fake_live))
    app = create_app(live_mode=True, settings_path="/tmp/test-settings")
    callbacks = {event.fn.__name__: event.fn for event in app.fns.values()}

    callbacks["do_reset"]()
    scenario_html, scenario_text, _, _ = callbacks["do_scenario"]("A. Happy mixed-intent")

    assert paths == ["/tmp/test-settings"] * 3
    assert "Review Transaction" in scenario_html
    assert scenario_text.startswith("Buy 5 DBS shares")

    fault_html, fault_text, _, _ = callbacks["do_scenario"]("C. Semantic discrepancy")

    assert "scripted" in fault_html.lower()
    assert "live" in fault_html.lower()
    assert fault_text == scenario_text
    assert paths == ["/tmp/test-settings"] * 3
