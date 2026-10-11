"""Presentation / view-model layer that transforms frozen backend records
into display-friendly structures for the Gradio UI.

These are pure data transforms — no business logic, no backend calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from dcta.ponder.serialization import content_sha256
from dcta.lifecycle.audit import AuditRecord
from dcta.lifecycle.records import Confirmation, Authorization, Receipt, Transfer
from dcta.mixed.gateway import MixedReceipt, MixedExecutionResult
from dcta.mixed.review import MixedReview
from dcta.mixed.session import MixedLifecycleState
from dcta.mixed.business import InvestmentPlan

from .signed_gateway import SignedExecutionResult

# --------------------------------------------------------------------------- #
#  Operation cards
# --------------------------------------------------------------------------- #


@dataclass
class OperationField:
    label: str
    value: str


@dataclass
class OperationCard:
    index: int
    goal: str  # "Investment" or "Transfer"
    action: str  # "BUY", "SELL", "SEND", etc.
    fields: list[OperationField] = field(default_factory=list)


def build_operation_cards(state: MixedLifecycleState) -> list[OperationCard]:
    """Extract operation cards from a mixed lifecycle state."""
    cards: list[OperationCard] = []
    if state.review is None:
        return cards
    review = state.review
    # Investment leg
    inv = review.investment
    cards.append(
        OperationCard(
            index=1,
            goal="Investment",
            action=inv.action,
            fields=[
                OperationField("Asset", inv.asset_label),
                OperationField("Quantity", f"{inv.quantity} shares"),
                OperationField("Simulation", "SIMULATED ORDER"),
            ],
        )
    )
    # Transfer leg(s)
    for i, t in enumerate(review.transfers, start=2):
        cards.append(
            OperationCard(
                index=i,
                goal="Transfer",
                action="SEND",
                fields=[
                    OperationField("Amount", f"{t.currency} {t.amount}"),
                    OperationField("From", t.source_label),
                    OperationField("To", t.target_label),
                ],
            )
        )
    return cards


# --------------------------------------------------------------------------- #
#  Lifecycle status steps
# --------------------------------------------------------------------------- #

StepStatus = Literal["pass", "fail", "pending", "warning", "blocked"]
STOPPED_STATUSES = frozenset({
    "UPSTREAM_STOP", "UNSUPPORTED", "LIMIT_EXCEEDED", "CONTRACT_ERROR",
    "SEMANTIC_FROZEN", "BLOCKED", "NEEDS_CLARIFICATION",
})


@dataclass
class LifecycleStep:
    index: int
    label: str
    status: StepStatus
    detail: str
    icon: str  # text icon for accessibility: PASS/FAIL/PENDING/WARN/BLOCK


def stop_reason(status: str, reason: str) -> str:
    """Translate a stopped backend state into a useful demo message."""
    if status == "UNSUPPORTED" and reason == "requires one investment and one transfer/payment predicate":
        return "This demo requires one investment and one money transfer or payment in the same command."
    if status == "NEEDS_CLARIFICATION":
        return "More information is needed; edit the command and click Submit."
    return reason or status.replace("_", " ").capitalize()


def build_lifecycle_steps(
    state: MixedLifecycleState,
    *,
    confirmation_accepted: bool = False,
    authorization_accepted: bool = False,
    biometric_completed: bool = False,
    signature_verified: bool = False,
    executed: bool = False,
) -> list[LifecycleStep]:
    """Build the zero-trust progression checklist from lifecycle state.

    Steps 6-8 reflect the *demo phase* (confirmation, authorization, execution)
    because the backend ``MixedLifecycleState`` status does not change after
    ``READY_FOR_CONFIRMATION`` — the demo orchestrator tracks those phases.
    """
    steps: list[LifecycleStep] = []
    s = state.status
    stopped = s in STOPPED_STATUSES

    def later_step(index: int, label: str, pending_detail: str) -> LifecycleStep:
        if stopped:
            return LifecycleStep(index, label, "blocked", "Transaction stopped", "BLOCK")
        return LifecycleStep(index, label, "pending", pending_detail, "PENDING")

    # Step 1: Input shield
    if s == "UPSTREAM_STOP" and state.reason == "PROMPT_INJECTION_SHIELD_BLOCKED":
        steps.append(LifecycleStep(1, "Input shield", "fail", "Prompt injection blocked — transaction stopped", "FAIL"))
    elif state.reason and "SHIELD" in state.reason:
        steps.append(LifecycleStep(1, "Input shield", "fail", state.reason, "FAIL"))
    else:
        steps.append(LifecycleStep(1, "Input shield", "pass", "Input shield passed", "PASS"))

    # Step 2: Intent interpreted
    if state.interpretation is not None:
        steps.append(LifecycleStep(2, "Intent interpreted", "pass", "Mixed intent extracted (investment + transfer)", "PASS"))
    elif stopped:
        steps.append(LifecycleStep(2, "Intent interpreted", "fail", stop_reason(s, state.reason), "FAIL"))
    else:
        steps.append(LifecycleStep(2, "Intent interpreted", "pending", "Awaiting interpretation", "PENDING"))

    # Step 3: Grounding resolved
    if state.grounding is not None:
        if state.grounding.clarifications:
            steps.append(LifecycleStep(3, "Grounding", "warning", "Ambiguous — clarification required", "WARN"))
        else:
            rev = state.grounding.revision
            detail = f"Grounding resolved (revision {rev})" if rev > 0 else "Grounding resolved"
            steps.append(LifecycleStep(3, "Grounding", "pass", detail, "PASS"))
    else:
        steps.append(later_step(3, "Grounding", "Awaiting grounding"))

    # Step 4: Semantic validation
    if state.semantic_gate is not None:
        result = state.semantic_decision.result if state.semantic_decision else "UNKNOWN"
        if state.semantic_gate.state == "ELIGIBLE_FOR_BUSINESS_CHECKS":
            steps.append(LifecycleStep(4, "Semantic validation", "pass", f"MATCH — eligible for business checks", "PASS"))
        elif state.semantic_gate.state == "FROZEN":
            steps.append(LifecycleStep(4, "Semantic validation", "fail", f"DISCREPANCY — transaction frozen", "FAIL"))
        else:
            steps.append(LifecycleStep(4, "Semantic validation", "warning", f"{result}", "WARN"))
    else:
        steps.append(later_step(4, "Semantic validation", "Awaiting validation"))

    # Step 5: Business/risk validation
    if state.business_result is not None:
        if state.review is not None:
            steps.append(LifecycleStep(5, "Business/risk validation", "pass", "PASS — eligible for confirmation", "PASS"))
        elif state.business_result.status == "BLOCKED":
            findings = [f.code for f in state.business_result.findings if f.result == "BLOCKED"]
            detail = f"BLOCKED — {findings[0] if findings else 'business policy'}"
            steps.append(LifecycleStep(5, "Business/risk validation", "fail", detail, "BLOCK"))
        elif state.business_result.status == "NEEDS_CLARIFICATION":
            prompts = dict.fromkeys(
                c.prompt
                for operation in state.business_result.operations
                for c in operation.clarifications
            )
            detail = "Needs clarification"
            if prompts:
                detail += " — " + "; ".join(prompts)
            detail += " Edit the command and click Submit."
            steps.append(LifecycleStep(5, "Business/risk validation", "warning", detail, "WARN"))
        else:
            steps.append(LifecycleStep(5, "Business/risk validation", "fail", state.business_result.status, "FAIL"))
    else:
        steps.append(later_step(5, "Business/risk validation", "Awaiting business validation"))

    # Step 6: Confirmation
    if stopped:
        steps.append(LifecycleStep(6, "Exact-bundle confirmation", "blocked", "Transaction stopped", "BLOCK"))
    elif confirmation_accepted:
        steps.append(LifecycleStep(6, "Exact-bundle confirmation", "pass", "Bundle confirmed", "PASS"))
    else:
        steps.append(LifecycleStep(6, "Exact-bundle confirmation", "pending", "Awaiting confirmation", "PENDING"))

    # Step 7: Authorization (biometric + crypto)
    if stopped:
        steps.append(LifecycleStep(7, "Biometric + crypto authorization", "blocked", "Transaction stopped", "BLOCK"))
    elif authorization_accepted and signature_verified:
        steps.append(LifecycleStep(7, "Biometric + crypto authorization", "pass", "Biometric verified + Ed25519 signature verified", "PASS"))
    elif signature_verified:
        steps.append(LifecycleStep(7, "Biometric + crypto authorization", "pending", "Signature verified — awaiting backend authorization", "PENDING"))
    elif confirmation_accepted and biometric_completed and not signature_verified:
        steps.append(LifecycleStep(7, "Biometric + crypto authorization", "pending", "Biometric done — awaiting signature", "PENDING"))
    elif confirmation_accepted and not biometric_completed:
        steps.append(LifecycleStep(7, "Biometric + crypto authorization", "pending", "Awaiting biometric verification", "PENDING"))
    else:
        steps.append(LifecycleStep(7, "Biometric + crypto authorization", "pending", "Awaiting authorization", "PENDING"))

    # Step 8: Execution
    if stopped:
        steps.append(LifecycleStep(8, "Zero-trust execution", "blocked", "Transaction stopped", "BLOCK"))
    elif executed:
        steps.append(LifecycleStep(8, "Zero-trust execution", "pass", "Executed via zero-trust gateway", "PASS"))
    else:
        steps.append(LifecycleStep(8, "Zero-trust execution", "pending", "Execution pending", "PENDING"))

    return steps


# --------------------------------------------------------------------------- #
#  Audit timeline
# --------------------------------------------------------------------------- #


@dataclass
class AuditEntryView:
    sequence: int
    event: str
    outcome: str
    artifact_hashes: list[str]
    causes: list[int]


def build_audit_timeline(records: tuple[AuditRecord, ...]) -> list[AuditEntryView]:
    views: list[AuditEntryView] = []
    for r in records:
        views.append(
            AuditEntryView(
                sequence=r.sequence,
                event=r.event,
                outcome=r.outcome,
                artifact_hashes=[a.sha256[:16] for a in r.artifacts],
                causes=[],  # causes are hashes; we map to sequences below
            )
        )
    return views


# --------------------------------------------------------------------------- #
#  Receipt view
# --------------------------------------------------------------------------- #


@dataclass
class ReceiptView:
    receipt_id: str
    status: str
    transfers: list[str]  # human-readable transfer lines
    investment: str | None  # human-readable investment line
    bundle_hash: str
    signature_verified: bool
    authorization_accepted: bool
    code: str
    bank_after_revision: int


def build_receipt_view(signed: SignedExecutionResult) -> ReceiptView:
    result = signed.result
    receipt = result.receipt
    transfers = [
        f"{t.currency} {t.amount} -> {t.target_label}" for t in receipt.transfers
    ]
    inv = receipt.investment
    investment = (
        f"{inv.action} {inv.plan.quantity} {inv.plan.asset_label} — SIMULATED INVESTMENT ORDER"
        if inv
        else None
    )
    return ReceiptView(
        receipt_id=receipt.authorization_sha256[:16],
        status=result.status,
        transfers=transfers,
        investment=investment,
        bundle_hash=receipt.review_sha256[:16],
        signature_verified=signed.signature_verified,
        authorization_accepted=signed.authorization_accepted,
        code=result.code,
        bank_after_revision=receipt.bank_after_revision,
    )


# --------------------------------------------------------------------------- #
#  Clarification view
# --------------------------------------------------------------------------- #


@dataclass
class ClarificationOption:
    entity_id: str
    name: str


@dataclass
class ClarificationView:
    prompt: str
    choice_id: str
    options: list[ClarificationOption]
    revision: int


def build_clarification_view(state: MixedLifecycleState) -> ClarificationView | None:
    if state.grounding is None or not state.grounding.clarifications:
        return None
    ch = state.grounding.clarifications[0]
    return ClarificationView(
        prompt=ch.prompt,
        choice_id=ch.id,
        options=[ClarificationOption(e.id, e.name) for e in ch.options],
        revision=state.grounding.revision,
    )


# --------------------------------------------------------------------------- #
#  Confirmation view
# --------------------------------------------------------------------------- #


@dataclass
class ConfirmationView:
    review_hash: str
    rendered_payload: str
    operations: list[OperationCard]
    notice: str


def build_confirmation_view(review: MixedReview) -> ConfirmationView:
    return ConfirmationView(
        review_hash=content_sha256(review)[:16],
        rendered_payload=review.rendered_payload,
        operations=[],  # filled by build_operation_cards via state
        notice="Confirming means you have reviewed this exact transaction bundle. This is NOT authorization.",
    )


# --------------------------------------------------------------------------- #
#  Demo state view — aggregated snapshot for the UI
# --------------------------------------------------------------------------- #


@dataclass
class DemoStateView:
    status: str
    reason: str
    operation_cards: list[OperationCard]
    lifecycle_steps: list[LifecycleStep]
    clarification: ClarificationView | None
    confirmation_available: bool
    confirmation_accepted: bool  # backend confirmation artifact accepted
    authorization_available: bool
    authorization_accepted: bool  # backend authorization artifact accepted
    execution_available: bool
    biometric_completed: bool
    signature_verified: bool
    receipt: ReceiptView | None
    audit_entries: list[AuditEntryView]
    audit_verified: bool
    error: str | None
    signing_available: bool = False


def short_hash(h: str, n: int = 16) -> str:
    return h[:n]
