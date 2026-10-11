"""Scripted wire-control provider for demo mode (no live API key required).

This is a clean re-implementation of the canned-choice pattern from the backend
test suite (tests/mixed/scripted.py).  It answers every hosted-model question
with deterministic canned responses so the full mixed lifecycle can run without
an OpenRouter API key.

This is NOT language-model evidence — it is a hackathon convenience so judges
can see the full zero-trust flow even without network access.
"""

import re
from dcta.validation.records import json_text


class ScriptedWireControl:
    """Drop-in replacement for the hosted DecisionsProvider.

    Returns canned choices for every stage of the mixed pipeline:
    role selection, canonical selection, scope, mixed relation, and
    mixed semantic validation.
    """

    model = "typesafe/jev-1.13"

    def __init__(self, statuses=None):
        self.requests = []
        self.statuses = statuses or {}

    # ------------------------------------------------------------------ #
    #  Public protocol method — matches DecisionsProvider.decide()
    # ------------------------------------------------------------------ #
    def decide(self, *, state, questions):
        self.requests.append({"state": state, "questions": questions})
        stage = state["trusted_controls"]["stage"]
        data = state["untrusted_data"]["state"]
        answers = {}

        # Extract known values from the transcript for role/canonical stages.
        if stage == "role":
            text = data["transcript"]
            quantity_match = re.search(r"(?:buy|sell|invest)\s+(\d+)", text, re.I)
            amount_match = re.search(r"SGD\s+(\d+)", text, re.I)
            self._quantity = quantity_match[1] if quantity_match else "5"
            self._amount = amount_match[1] if amount_match else "50"

        for key, q in questions.items():
            if stage == "role":
                c = next(
                    c for c in data["candidate_inventory"] if c["candidate_id"] == key
                )
                choice = {
                    "SGD": "currency",
                    self._quantity: "asset_quantity",
                    self._amount: "transfer_amount",
                    "DBS": "asset",
                    "Sarah": "beneficiary",
                    "John": "beneficiary",
                    "savings": "source_account",
                }.get(c["text"], "NONE")

            elif stage == "canonical":
                choice = next(
                    c["candidate_id"]
                    for cluster in data["canonical_clusters"]
                    if cluster["cluster_id"] == key
                    for c in cluster["candidates"]
                )

            elif stage == "scope":
                choice = "NESTED_DATA"

            elif stage == "mixed_relation":
                if key == "binding":
                    choice = "mixed:p0"
                elif key.startswith("action:"):
                    choice = next(
                        c for c in q["criteria"] if c != "UNSPECIFIED"
                    )
                else:
                    a = next(
                        a for a in data["anchors"] if "anchor:" + a["id"] == key
                    )
                    choice = (
                        "investment_command"
                        if a["evidence"]["text"].casefold()
                        in {"buy", "sell", "invest"}
                        else "transfer_command"
                    )

            else:
                # mixed_semantic stage
                choice = (
                    "source:full"
                    if key.endswith(":evidence")
                    else self.statuses.get(key, "MATCH")
                )

            answers[key] = {"type": "choice", "choice": choice}

        return {
            "request": {"body": {"state": state, "questions": questions}},
            "http_status": 200,
            "raw_response": {
                "model": "typesafe/jev-1.13-20260917",
                "provider": "TypeSafe",
                "answers": answers,
                "usage": {"cost": 0},
            },
            "error_class": None,
            "latency_ms": 0,
            "retries": 0,
        }
