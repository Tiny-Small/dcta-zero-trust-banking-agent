"""Gradio buttons follow the signed gateway's current capabilities."""

from demo_ui.app import create_app


def test_later_stage_buttons_follow_verified_artifacts():
    app = create_app()
    callbacks = {event.fn.__name__: event.fn for event in app.fns.values()}
    refresh = callbacks["refresh_controls"]

    assert not refresh()[3]["interactive"]  # authorize
    callbacks["do_scenario"]("A. Happy mixed-intent")
    controls = refresh()
    assert controls[0]["interactive"]  # confirm
    assert not controls[3]["interactive"]
    assert not controls[4]["interactive"]  # execute

    callbacks["do_confirm"]()
    assert not refresh()[3]["interactive"]
    callbacks["do_biometric"]()
    controls = refresh()
    assert controls[2]["interactive"]  # sign
    assert not controls[3]["interactive"]  # authorize

    callbacks["do_sign"]()
    controls = refresh()
    assert controls[3]["interactive"]
    assert not controls[4]["interactive"]

    callbacks["do_authorize"]()
    controls = refresh()
    assert controls[4]["interactive"]

    callbacks["do_execute"]()
    controls = refresh()
    assert not controls[4]["interactive"]
    assert controls[5]["interactive"]  # duplicate
