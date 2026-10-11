"""Gradio app for the DCTA zero-trust transaction demo.

Launch:
    python -m demo_ui.app                    # demo mode (scripted, no API key)
    python -m demo_ui.app --live             # live mode (requires OpenRouter key)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure backend src is importable.
_root = Path(__file__).resolve().parents[1]
_src = _root / "src"
DEFAULT_SETTINGS_PATH = None
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

import gradio as gr

from .orchestrator import DemoSession
from .scenarios import SCENARIOS, get_scenario
from .scripted_provider import ScriptedWireControl
from .view_models import DemoStateView
from .escaping import esc

# --------------------------------------------------------------------------- #
#  HTML renderers
# --------------------------------------------------------------------------- #

BANK_CSS = """
<style>
.dcta-container, .dcta-container * { font-family: 'Segoe UI', Arial, sans-serif; }
.dcta-container { max-width: 1100px; margin: 0 auto; color: #1d2939 !important; }
.dcta-container * { color: #1d2939; }
.dcta-header, .dcta-header * { color: white !important; }
.dcta-header { background: #0a2e5c; padding: 18px 28px; border-radius: 12px; margin-bottom: 16px; }
.dcta-header h1 { margin: 0; font-size: 22px; font-weight: 700; }
.dcta-header p { margin: 4px 0 0; font-size: 13px; opacity: 0.8; }
.dcta-cards { display: flex; gap: 12px; margin: 12px 0; }
.dcta-card { flex: 1; border: 1px solid #d0d5dd; border-radius: 10px; padding: 14px; background: #1a1a2e; color: #e0e0e0 !important; }
.dcta-card * { color: #e0e0e0; }
.dcta-card-header { font-size: 12px; font-weight: 700; text-transform: uppercase; color: #9fa8da !important; margin-bottom: 8px; }
.dcta-card-action { font-size: 18px; font-weight: 700; color: #82b1ff !important; margin-bottom: 8px; }
.dcta-card-field { display: flex; justify-content: space-between; padding: 3px 0; font-size: 13px; border-bottom: 1px solid #2a2a3e; }
.dcta-card-field:last-child { border-bottom: none; }
.dcta-card-field-label { color: #9fa8da !important; }
.dcta-card-field-value { font-weight: 600; color: #e0e0e0 !important; }
.dcta-card-sim { font-size: 11px; color: #ffb74d !important; font-weight: 600; }
.dcta-lifecycle { background: #1a1a2e; border: 1px solid #2a2a3e; border-radius: 10px; padding: 14px; margin: 12px 0; color: #e0e0e0 !important; }
.dcta-lifecycle * { color: #e0e0e0; }
.dcta-lifecycle-title { font-size: 12px; font-weight: 700; text-transform: uppercase; color: #9fa8da !important; margin-bottom: 10px; }
.dcta-step { display: flex; align-items: center; gap: 8px; padding: 5px 0; font-size: 13px; }
.dcta-step-icon { width: 22px; height: 22px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-weight: 700; font-size: 10px; flex-shrink: 0; }
.dcta-step-pass { background: #1b3a2e; color: #66bb6a !important; border: 1px solid #2e5e3e; }
.dcta-step-fail { background: #3a1a1a; color: #ef5350 !important; border: 1px solid #5e2e2e; }
.dcta-step-pending { background: #2a2a3e; color: #9fa8da !important; border: 1px solid #3a3a4e; }
.dcta-step-warning { background: #3a2e1a; color: #ffb74d !important; border: 1px solid #5e4e2e; }
.dcta-step-blocked { background: #3a1a1a; color: #ef5350 !important; border: 1px solid #5e2e2e; }
.dcta-step-label { font-weight: 600; color: #e0e0e0 !important; }
.dcta-step-detail { color: #9fa8da !important; font-size: 12px; }
.dcta-panel { border: 1px solid #2a2a3e; border-radius: 10px; padding: 16px; margin: 12px 0; background: #1a1a2e; color: #e0e0e0 !important; }
.dcta-panel * { color: #e0e0e0; }
.dcta-panel-title { font-size: 14px; font-weight: 700; color: #82b1ff !important; margin-bottom: 10px; }
.dcta-biometric { border: 2px dashed #82b1ff; border-radius: 12px; padding: 20px; text-align: center; margin: 12px 0; background: #16213e; color: #e0e0e0 !important; }
.dcta-biometric * { color: #e0e0e0; }
.dcta-biometric-icon { font-size: 48px; margin-bottom: 8px; }
.dcta-audit { font-size: 12px; font-family: 'Courier New', monospace; color: #9fa8da !important; }
.dcta-audit-entry { display: flex; gap: 8px; padding: 3px 0; border-bottom: 1px solid #2a2a3e; }
.dcta-audit-seq { color: #9fa8da !important; min-width: 28px; }
.dcta-audit-event { font-weight: 600; color: #e0e0e0 !important; min-width: 200px; }
.dcta-audit-outcome { color: #9fa8da !important; }
.dcta-arch { font-size: 12px; line-height: 1.6; color: #9fa8da !important; }
.dcta-arch-box { border: 1px solid #2a2a3e; border-radius: 6px; padding: 6px 10px; margin: 2px 0; background: #1a1a2e; color: #9fa8da !important; }
.dcta-arch-box-untrusted { border-left: 4px solid #ef5350; }
.dcta-arch-box-trusted { border-left: 4px solid #66bb6a; }
.dcta-arch-box-ai { border-left: 4px solid #82b1ff; }
.dcta-key-concept { background: #3a2e1a; border: 1px solid #5e4e2e; border-radius: 8px; padding: 10px; margin: 8px 0; font-size: 13px; font-weight: 600; color: #ffb74d !important; text-align: center; }
.dcta-error { background: #3a1a1a; border: 1px solid #5e2e2e; border-radius: 8px; padding: 10px; margin: 8px 0; color: #ef5350 !important; font-size: 13px; }
.dcta-notice { background: #1a2a3e; border: 1px solid #2e4e6e; border-radius: 8px; padding: 10px; margin: 8px 0; color: #82b1ff !important; font-size: 13px; }
.dcta-sig { font-family: 'Courier New', monospace; font-size: 12px; color: #9fa8da !important; }
.dcta-receipt { border: 2px solid #66bb6a; border-radius: 10px; padding: 16px; margin: 12px 0; background: #1b3a2e; color: #e0e0e0 !important; }
.dcta-receipt * { color: #e0e0e0; }
.dcta-mode-badge { display: inline-block; padding: 4px 12px; border-radius: 6px; font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }
.dcta-mode-live { background: #3a1a1a; color: #ef5350 !important; border: 1px solid #5e2e2e; }
.dcta-mode-scripted { background: #1b3a2e; color: #66bb6a !important; border: 1px solid #2e5e3e; }
</style>
"""

STEP_ICONS = {
    "pass": ("PASS", "dcta-step-pass"),
    "fail": ("FAIL", "dcta-step-fail"),
    "pending": ("\u25cb", "dcta-step-pending"),
    "warning": ("!", "dcta-step-warning"),
    "blocked": ("BLK", "dcta-step-blocked"),
}


def render_mode_badge(live_mode: bool) -> str:
    """Non-spoofable LIVE vs SCRIPTED mode badge.

    The value is sourced from the trusted server-side ``live_mode`` flag
    (set by ``--live`` CLI argument), never from user input or URL parameters.
    """
    if live_mode:
        return (
            '<span class="dcta-mode-badge dcta-mode-live">'
            "LIVE API \u2014 real GenAI calls"
            "</span>"
        )
    return (
        '<span class="dcta-mode-badge dcta-mode-scripted">'
        "SCRIPTED \u2014 no API calls (demo mode)"
        "</span>"
    )


def render_operation_cards(view: DemoStateView) -> str:
    if not view.operation_cards:
        if view.status in ("UPSTREAM_STOP", "SEMANTIC_FROZEN", "BLOCKED", "CONTRACT_ERROR"):
            return '<p style="color:#667085;font-size:13px;">No validated operations to display \u2014 transaction stopped before confirmation.</p>'
        return ""
    cards_html = []
    for card in view.operation_cards:
        fields = "".join(
            f'<div class="dcta-card-field"><span class="dcta-card-field-label">{esc(f.label)}</span>'
            f'<span class="dcta-card-field-value">{esc(f.value)}</span></div>'
            for f in card.fields
        )
        cards_html.append(
            f'<div class="dcta-card"><div class="dcta-card-header">Operation {card.index} \u2014 {esc(card.goal)}</div>'
            f'<div class="dcta-card-action">{esc(card.action)}</div>{fields}</div>'
        )
    return f'<div class="dcta-cards">{"".join(cards_html)}</div>'


def render_lifecycle(view: DemoStateView) -> str:
    steps_html = []
    for step in view.lifecycle_steps:
        icon, css = STEP_ICONS.get(step.status, STEP_ICONS["pending"])
        steps_html.append(
            f'<div class="dcta-step"><span class="dcta-step-icon {css}">{icon}</span>'
            f'<span class="dcta-step-label">{esc(step.label)}</span>'
            f'<span class="dcta-step-detail">\u2014 {esc(step.detail)}</span></div>'
        )
    return (
        '<div class="dcta-lifecycle"><div class="dcta-lifecycle-title">'
        "Zero-Trust Lifecycle</div>" + "".join(steps_html) + "</div>"
    )


def render_clarification(view: DemoStateView) -> str:
    if view.clarification is None:
        return ""
    ch = view.clarification
    options = " | ".join(f"[{esc(o.name)}]" for o in ch.options)
    return (
        f'<div class="dcta-panel"><div class="dcta-panel-title">Clarification Required</div>'
        f'<p style="font-size:14px;font-weight:600;">{esc(ch.prompt)}</p>'
        f'<p style="font-size:13px;color:#667085;">Options: {options}</p>'
        f'<p style="font-size:12px;color:#667085;">Use the clarification buttons below to select an entity.</p></div>'
    )


def render_confirmation(view: DemoStateView) -> str:
    if view.confirmation_accepted:
        return '<div class="dcta-notice">Transaction confirmed. Proceed to simulated biometric verification.</div>'
    if view.status != "READY_FOR_CONFIRMATION" or not view.confirmation_available:
        return ""
    return (
        '<div class="dcta-panel"><div class="dcta-panel-title">Review Transaction</div>'
        '<p style="font-size:13px;color:#667085;">Confirming means you have reviewed this exact transaction bundle.</p>'
        '<p style="font-size:13px;color:#b54708;font-weight:600;">This is NOT authorization.</p></div>'
    )


def render_biometric(view: DemoStateView) -> str:
    if not view.confirmation_accepted:
        return ""
    if view.biometric_completed:
        return (
            '<div class="dcta-panel"><div class="dcta-panel-title">Simulated Biometric Verification</div>'
            '<div class="dcta-biometric"><div class="dcta-biometric-icon">\u2705</div>'
            '<p style="font-size:13px;font-weight:600;">Simulated FaceID verification complete</p></div></div>'
        )
    return (
        '<div class="dcta-panel"><div class="dcta-panel-title">Simulated Biometric Verification</div>'
        '<div class="dcta-biometric"><div class="dcta-biometric-icon">\U0001F464</div>'
        '<p style="font-size:13px;font-weight:600;">Simulated FaceID</p>'
        '<p style="font-size:11px;color:#667085;">This is a hackathon mock, not real biometric SDK.</p></div></div>'
    )


def render_signature(view: DemoStateView) -> str:
    if not view.signature_verified:
        return ""
    return (
        '<div class="dcta-panel"><div class="dcta-panel-title">Demo Security Status</div>'
        '<div style="font-size:13px;">'
        '\u2705 Simulated biometric verification complete<br>'
        '\u2705 Transaction bundle signed with demo Ed25519 key<br>'
        '\u2705 Signature verified by SignedExecutionGateway (public-key-only)<br>'
        + ('\u2705 Backend authorization accepted<br>' if view.authorization_accepted else 'Backend authorization pending<br>')
        + '</div></div>'
    )


def render_receipt(view: DemoStateView) -> str:
    if view.receipt is None:
        return ""
    r = view.receipt
    transfers = "<br>".join(f"Transfer: {esc(t)}" for t in r.transfers)
    inv = f"<br>Investment: {esc(r.investment)}" if r.investment else ""
    already = ""
    if r.status == "ALREADY_EXECUTED":
        already = '<p style="font-size:13px;color:#b54708;font-weight:600;">ALREADY_EXECUTED \u2014 no second debit or investment order.</p>'
    return (
        f'<div class="dcta-receipt"><div class="dcta-panel-title">Transaction {"Completed" if r.status == "SUCCEEDED" else esc(r.status)}</div>'
        f'{already}'
        f'<div style="font-size:14px;">{transfers}{inv}</div>'
        f'<div class="dcta-sig" style="margin-top:8px;">'
        f'Receipt ID: {esc(r.receipt_id)}<br>'
        f'Bundle hash: {esc(r.bundle_hash)}<br>'
        f'Signature verified by signed gateway: {"Yes" if r.signature_verified else "No"}<br>'
        f'Backend authorization accepted: {"Yes" if r.authorization_accepted else "No"}<br>'
        f'Code: {esc(r.code)}</div></div>'
    )


def render_audit(view: DemoStateView) -> str:
    if not view.audit_entries:
        return ""
    entries = []
    for e in view.audit_entries:
        entries.append(
            f'<div class="dcta-audit-entry"><span class="dcta-audit-seq">{e.sequence}</span>'
            f'<span class="dcta-audit-event">{esc(e.event)}</span>'
            f'<span class="dcta-audit-outcome">{esc(e.outcome)}</span></div>'
        )
    verified = "\u2705 Audit chain verified" if view.audit_verified else "\u274C Audit chain BROKEN"
    return (
        '<div class="dcta-panel"><div class="dcta-panel-title">Audit Timeline</div>'
        f'<div class="dcta-audit">{"".join(entries)}</div>'
        f'<div style="font-size:12px;color:#027a48;margin-top:6px;">{verified}</div></div>'
    )


def render_architecture() -> str:
    return (
        '<div class="dcta-panel"><div class="dcta-panel-title">Architecture / Trust Boundaries</div>'
        '<div class="dcta-arch">'
        '<div class="dcta-arch-box dcta-arch-box-untrusted">UNTRUSTED USER INPUT</div>'
        '<div style="text-align:center;color:#667085;">\u2193</div>'
        '<div class="dcta-arch-box dcta-arch-box-ai">Prompt-Injection Shield</div>'
        '<div style="text-align:center;color:#667085;">\u2193</div>'
        '<div class="dcta-arch-box dcta-arch-box-ai">Probabilistic Interpretation (GenAI)</div>'
        '<div style="text-align:center;color:#667085;">\u2193</div>'
        '<div class="dcta-arch-box dcta-arch-box-ai">Grounding + Independent Semantic Validator</div>'
        '<div style="text-align:center;color:#667085;">\u2193</div>'
        '<div class="dcta-arch-box dcta-arch-box-trusted">Deterministic Business/Risk Gate</div>'
        '<div style="text-align:center;color:#667085;">\u2193</div>'
        '<div class="dcta-arch-box dcta-arch-box-trusted">Exact Human Confirmation</div>'
        '<div style="text-align:center;color:#667085;">\u2193</div>'
        '<div class="dcta-arch-box dcta-arch-box-trusted">Simulated Biometric + Ed25519 Sign &amp; Verify</div>'
        '<div style="text-align:center;color:#667085;">\u2193</div>'
        '<div class="dcta-arch-box dcta-arch-box-trusted">SignedExecutionGateway (public-key-only)</div>'
        '<div style="text-align:center;color:#667085;">\u2193</div>'
        '<div class="dcta-arch-box dcta-arch-box-trusted">Frozen MixedGateway</div>'
        '<div style="text-align:center;color:#667085;">\u2193</div>'
        '<div class="dcta-arch-box dcta-arch-box-trusted">Atomic / Idempotent Mock Execution</div>'
        '<div style="text-align:center;color:#667085;">\u2193</div>'
        '<div class="dcta-arch-box dcta-arch-box-trusted">Immutable Audit</div>'
        '</div>'
        '<div class="dcta-key-concept">GENAI GENERATES DRAFTS. GENAI NEVER RECEIVES EXECUTION AUTHORITY.</div>'
        '</div>'
    )


def render_error(view: DemoStateView) -> str:
    if view.error is None:
        return ""
    return f'<div class="dcta-error">{esc(view.error)}</div>'


def render_full(view: DemoStateView) -> str:
    """Render the complete demo state as a single HTML block."""
    parts = [BANK_CSS, '<div class="dcta-container">']
    parts.append(render_error(view))
    parts.append(render_operation_cards(view))
    parts.append(render_lifecycle(view))
    parts.append(render_clarification(view))
    parts.append(render_confirmation(view))
    parts.append(render_biometric(view))
    parts.append(render_signature(view))
    parts.append(render_receipt(view))
    parts.append(render_audit(view))
    parts.append("</div>")
    return "".join(parts)


# --------------------------------------------------------------------------- #
#  Session container (mutable wrapper to avoid nonlocal issues)
# --------------------------------------------------------------------------- #

class SessionContainer:
    """Mutable container holding the current DemoSession."""
    def __init__(self, live_mode=False, settings_path=None):
        self.live_mode = live_mode
        self.settings_path = settings_path
        self.reset()

    def get(self):
        return self.s

    def set(self, new_s):
        self.s = new_s

    def reset(self):
        self.s = (
            DemoSession.live(self.settings_path) if self.live_mode else DemoSession()
        )


# --------------------------------------------------------------------------- #
#  Gradio app
# --------------------------------------------------------------------------- #

def _clarify_labels(view: DemoStateView) -> tuple[str, str]:
    """Extract button labels from the current view's clarification options."""
    if view.clarification and len(view.clarification.options) >= 2:
        opts = view.clarification.options
        return f"Select: {opts[0].name}", f"Select: {opts[1].name}"
    return "Select First Option", "Select Second Option"


def create_app(live_mode: bool = False, settings_path: str | None = None):
    """Create and return the Gradio Blocks app."""
    container = SessionContainer(live_mode, settings_path)

    def do_submit(text: str):
        view = container.get().submit_text(text)
        return render_full(view), *_clarify_labels(view)

    def do_scenario(scenario_label: str):
        key = (scenario_label or "A").split(".")[0].strip()
        scenario = get_scenario(key)
        if scenario is None:
            view = container.get()._build_view()
            return render_full(view), "", *_clarify_labels(view)
        if scenario.fault_statuses and container.live_mode:
            current = container.get()
            current_text = (
                current.state.compilation.input_snapshot.current_source.text
                if current.state is not None else ""
            )
            view = current._error_view(
                "This scenario uses scripted fault injection. Run it in scripted mode."
            )
            return render_full(view), current_text, *_clarify_labels(view)
        if scenario.fault_statuses:
            provider = ScriptedWireControl(statuses=scenario.fault_statuses)
            from dcta.mixed.gateway import MixedGateway
            from dcta.mixed.session import MixedTextLifecycle
            from dcta.business.mock import mock_bank, mock_policy
            from dcta.mixed.business import mock_investment_state, mock_investment_policy
            gw = MixedGateway(mock_bank(), mock_policy(), mock_investment_state(), mock_investment_policy())
            lc = MixedTextLifecycle(provider, gw)
            container.set(DemoSession(provider=provider, gateway=gw, lifecycle=lc))
        else:
            container.reset()
        view = container.get().submit_text(scenario.text)
        return render_full(view), scenario.text, *_clarify_labels(view)

    def do_clarify(entity_id: str):
        s = container.get()
        if s.state is None or s.state.status != "NEEDS_GROUNDING" or not s.state.grounding.clarifications:
            view = s._build_view()
            return render_full(view), *_clarify_labels(view)
        ch = s.state.grounding.clarifications[0]
        view = s.resolve_grounding(ch.id, entity_id)
        return render_full(view), *_clarify_labels(view)

    def do_confirm():
        view = container.get().confirm_transaction()
        return render_full(view), *_clarify_labels(view)

    def do_reject():
        view = container.get().reject_transaction()
        return render_full(view), *_clarify_labels(view)

    def do_biometric():
        view = container.get().simulate_biometric()
        return render_full(view), *_clarify_labels(view)

    def do_sign():
        view = container.get().sign_transaction()
        return render_full(view), *_clarify_labels(view)

    def do_authorize():
        view = container.get().authorize_signed()
        return render_full(view), *_clarify_labels(view)

    def do_execute():
        view = container.get().execute()
        return render_full(view), *_clarify_labels(view)

    def do_execute_again():
        view = container.get().execute_again()
        return render_full(view), *_clarify_labels(view)

    def do_reset():
        container.reset()
        view = container.get()._build_view()
        return render_full(view), "", *_clarify_labels(view)

    with gr.Blocks(
        title="DCTA \u2014 Direct Conversational Transaction Agent",
    ) as app:
        gr.HTML(
            '<div class="dcta-header">'
            "<h1>DCTA \u2014 Direct Conversational Transaction Agent</h1>"
            "<p>Tencent Cloud AI Singapore Hackathon 2026 \u2014 DBS Banking Track</p>"
            + f'<div style="margin-top:8px;">{render_mode_badge(live_mode)}</div>'
            + "</div>"
            + BANK_CSS
        )

        with gr.Row():
            text_input = gr.Textbox(
                label="Transaction Command",
                placeholder="Buy 5 DBS shares and send SGD 50 to Sarah from savings.",
                lines=2,
                scale=4,
            )
            with gr.Column(scale=1):
                submit_btn = gr.Button("Submit", variant="primary")
                reset_btn = gr.Button("Reset", variant="secondary")

        with gr.Row():
            scenario_dropdown = gr.Dropdown(
                choices=[f"{s.key}. {s.label}" for s in SCENARIOS],
                label="Demo Scenarios",
                info="Pre-built scenarios for presentation",
                scale=3,
            )
            scenario_btn = gr.Button("Load Scenario", variant="secondary", scale=1)

        # Main output area.
        output_html = gr.HTML(value=render_full(container.get()._build_view()))

        # Clarification buttons row.
        gr.HTML('<div style="border-top:1px solid #d0d5dd;margin:8px 0;"></div>')
        gr.HTML('<p style="font-size:12px;font-weight:700;text-transform:uppercase;color:#475467;margin:4px 0;">Clarification (when ambiguous)</p>')
        with gr.Row():
            clarify_a_btn = gr.Button("Select First Option", variant="secondary", size="sm")
            clarify_b_btn = gr.Button("Select Second Option", variant="secondary", size="sm")

        # Action buttons row.
        gr.HTML('<div style="border-top:1px solid #d0d5dd;margin:8px 0;"></div>')
        gr.HTML('<p style="font-size:12px;font-weight:700;text-transform:uppercase;color:#475467;margin:4px 0;">Transaction Actions</p>')
        with gr.Row():
            confirm_btn = gr.Button("Confirm Bundle", variant="primary", interactive=False)
            reject_btn = gr.Button("Reject", variant="stop", interactive=False)
        with gr.Row():
            biometric_btn = gr.Button("Simulate FaceID", variant="secondary", interactive=False)
            sign_btn = gr.Button("Sign & Verify", variant="secondary", interactive=False)
            authorize_btn = gr.Button("Authorize", variant="primary", interactive=False)
        with gr.Row():
            execute_btn = gr.Button("Execute", variant="primary", interactive=False)
            execute_again_btn = gr.Button("Execute Again (Duplicate)", variant="stop", interactive=False)

        # Architecture panel (always visible at bottom).
        gr.HTML(render_architecture())

        # Event handlers.
        _clarify_outputs = [output_html, clarify_a_btn, clarify_b_btn]
        _scenario_outputs = [output_html, text_input, clarify_a_btn, clarify_b_btn]
        _action_outputs = [output_html, clarify_a_btn, clarify_b_btn]
        _control_outputs = [
            confirm_btn, biometric_btn, sign_btn, authorize_btn,
            execute_btn, execute_again_btn, reject_btn,
        ]

        def refresh_controls():
            s = container.get()
            view = s._build_view()
            duplicate_available = (
                view.receipt is not None
                and view.receipt.status in {"SUCCEEDED", "ALREADY_EXECUTED"}
                and s.gateway.is_current_authorization(
                    s.signed_authorization, s.signature_artifact
                )
            )
            reject_available = (
                view.status == "READY_FOR_CONFIRMATION"
                and view.receipt is None
                and (view.confirmation_available or view.confirmation_accepted)
            )
            return (
                gr.update(interactive=view.confirmation_available),
                gr.update(interactive=view.confirmation_accepted and not view.biometric_completed),
                gr.update(interactive=view.signing_available and not view.signature_verified),
                gr.update(interactive=view.authorization_available),
                gr.update(interactive=view.execution_available),
                gr.update(interactive=duplicate_available),
                gr.update(interactive=reject_available),
            )

        events = [
            submit_btn.click(fn=do_submit, inputs=[text_input], outputs=_clarify_outputs),
            text_input.submit(fn=do_submit, inputs=[text_input], outputs=_clarify_outputs),
        ]

        events.append(scenario_btn.click(fn=do_scenario, inputs=[scenario_dropdown], outputs=_scenario_outputs))

        def clarify_option(index: int, current_text: str | None):
            s = container.get()
            if s.state and s.state.grounding and s.state.grounding.clarifications:
                ch = s.state.grounding.clarifications[0]
                if len(ch.options) > index:
                    submitted_text = s.state.compilation.input_snapshot.current_source.text
                    if current_text is not None and current_text != submitted_text:
                        view = s._error_view(
                            "Command changed since submission. Click Submit to check the edited command before selecting a beneficiary."
                        )
                    else:
                        view = s.resolve_grounding(ch.id, ch.options[index].id)
                    return render_full(view), *_clarify_labels(view)
            view = s._build_view()
            return render_full(view), *_clarify_labels(view)

        def clarify_first(current_text: str | None = None):
            return clarify_option(0, current_text)

        def clarify_second(current_text: str | None = None):
            return clarify_option(1, current_text)

        events.extend([
            clarify_a_btn.click(fn=clarify_first, inputs=[text_input], outputs=_action_outputs),
            clarify_b_btn.click(fn=clarify_second, inputs=[text_input], outputs=_action_outputs),
            confirm_btn.click(fn=do_confirm, inputs=[], outputs=_action_outputs),
            reject_btn.click(fn=do_reject, inputs=[], outputs=_action_outputs),
            biometric_btn.click(fn=do_biometric, inputs=[], outputs=_action_outputs),
            sign_btn.click(fn=do_sign, inputs=[], outputs=_action_outputs),
            authorize_btn.click(fn=do_authorize, inputs=[], outputs=_action_outputs),
            execute_btn.click(fn=do_execute, inputs=[], outputs=_action_outputs),
            execute_again_btn.click(fn=do_execute_again, inputs=[], outputs=_action_outputs),
            reset_btn.click(fn=do_reset, inputs=[], outputs=_scenario_outputs),
        ])
        for event in events:
            event.then(fn=refresh_controls, inputs=[], outputs=_control_outputs)

    return app


def main():
    parser = argparse.ArgumentParser(description="DCTA Demo UI")
    parser.add_argument(
        "--settings", default=None,
        help="Optional explicit settings file for live API mode (otherwise use environment variables)",
    )
    parser.add_argument("--live", action="store_true", help="Use live OpenRouter API")
    parser.add_argument("--port", type=int, default=7860, help="Port to launch on")
    args = parser.parse_args()

    app = create_app(live_mode=args.live, settings_path=args.settings)
    app.launch(server_port=args.port, share=False, theme=gr.themes.Soft())


if __name__ == "__main__":
    main()
