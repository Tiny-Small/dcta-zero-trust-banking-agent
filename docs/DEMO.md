# Demo guide

## Launch

Install with `.[demo,test]` as shown in the [README](../README.md), then run:

```bash
.venv/bin/python -m demo_ui
```

This starts SCRIPTED DEMO on port 7860. Add `--port 8080` to change the port. The server-side mode badge identifies scripted or live behavior; user text cannot set it.

LIVE uses a locally supplied `OPENROUTER_API_KEY` and the pinned `typesafe/jev-1.13` model:

```bash
OPENROUTER_API_KEY=<your-local-key> .venv/bin/python -m demo_ui --live
```

You may pass `--settings PATH` to select a local settings file explicitly. There is no implicit `.envrc` lookup. LIVE sends real model requests; SCRIPTED DEMO sends none.

## Walkthrough

1. Select **A. Happy mixed-intent**. Review the separate investment and transfer cards and the lifecycle statuses. Confirm the exact bundle, run the simulated biometric step, choose Sign & Verify, Authorize, then Execute. The receipt and audit panel describe the mock outcome.
2. Select **B. Ambiguous beneficiary**. Choose one of the two synthetic Johns. Observe a new grounding revision and a fresh validation result before confirmation becomes available.
3. Select **C. Semantic discrepancy** in SCRIPTED DEMO. The injected validator discrepancy freezes the transaction. It is a demonstration fault, not a claim about LIVE model accuracy.
4. Select **D. Business/risk failure**. The synthetic policy blocks the SGD 5,000 transfer.
5. Select **E. Prompt injection**. The shield stops the malicious memo before provider progression.
6. Select **F. Duplicate execution**. Complete the signed path once, then click Execute Again. The second result is `ALREADY_EXECUTED`; the same receipt is returned without a second debit or simulated order.

The biometric step is a UI simulation. The signing step uses an ephemeral Ed25519 keypair. The demo security-status panel describes those checks separately from backend audit records. No banking or brokerage service is contacted.
