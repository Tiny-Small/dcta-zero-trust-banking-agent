# DCTA: Zero-Trust Conversational Transaction Demo

A text-first Direct Conversational Transaction Agent for the Tencent Cloud AI Singapore Hackathon 2026 DBS challenge. It turns a bounded banking request into a reviewable transaction proposal, then requires independent checks and explicit human actions before any **mock** execution. The demo supports a transfer combined with a simulated investment order.

The value proposition is a visible trust boundary: model output proposes meaning, while deterministic checks, an exact-bundle review, a signature-verifying gateway, and an audit trail control execution.

## Quick start

Requires Python 3.12 or newer.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[demo,test]'
.venv/bin/python -m demo_ui
```

Open the local URL printed by Gradio. The default **SCRIPTED DEMO** uses deterministic responses and needs no API key or network inference. It still runs the same shield, lifecycle gates, signing actions, and mock execution.

For **LIVE** TypeSafe Jev inference through the configured OpenRouter Decisions endpoint, supply a credential in your local environment:

```bash
OPENROUTER_API_KEY=<your-local-key> .venv/bin/python -m demo_ui --live
```

`JEV_MODEL` is optional; LIVE accepts only `typesafe/jev-1.13`. An explicit `--settings PATH` can read a local file containing literal `OPENROUTER_API_KEY` and `JEV_MODEL` assignments. No settings file is loaded implicitly. See [.env.example](.env.example) for variable names; never commit a real credential.

## Demo scenarios

| Scenario | What to observe |
|---|---|
| A — Happy mixed intent | Buy 5 synthetic DBS shares and transfer SGD 50; confirm, simulate biometric, sign, authorize, execute. |
| B — Ambiguous beneficiary | Choose between two synthetic Johns; the grounding revision and downstream checks are refreshed. |
| C — Semantic discrepancy | SCRIPTED fault injection freezes the proposal before confirmation. |
| D — Business/risk block | SGD 5,000 exceeds the synthetic per-transaction policy limit. |
| E — Prompt injection | The shield stops the injected memo before model progression. |
| F — Duplicate execution | “Execute Again” uses the signed gateway and returns `ALREADY_EXECUTED` without a second debit or order. |

The UI badge distinguishes **SCRIPTED — no API calls** from **LIVE API — real GenAI calls**. Scenario C is intentionally a scripted fault demonstration; LIVE mode does not silently substitute its canned response.

## Architecture and tests

Untrusted text → prompt shield → Parser+Jev/Ping and Ponder intent assembly → grounding → independent semantic validation → deterministic business/risk gate → exact human confirmation → simulated biometric → Ed25519 sign-off → public-key-only SignedExecutionGateway verification → backend authorization → atomic/idempotent mock execution → audit.

See [architecture](docs/ARCHITECTURE.md), [demo guide](docs/DEMO.md), [security model](docs/SECURITY.md), and [limitations](docs/LIMITATIONS.md).

```bash
.venv/bin/python -m pytest -q
```

The submission tests cover the signed gateway, stale/tampered evidence, shielding, mixed-intent gates, LIVE transport construction, rendering safety, and wheel contents. The demo is **not a banking service**: all account and directory entries are synthetic, identity and biometric steps are simulated, and no real transfer or trade occurs.

## Contribution note

The development repository describes the initial Gradio demo layer as CodeBuddy-assisted. This acknowledgement does not attribute the signed-gateway remediation or backend research to CodeBuddy, and does not claim an exported CodeBuddy session record is included here.
