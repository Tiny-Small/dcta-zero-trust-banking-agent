# Known limitations

## Banking and execution scope

- All directory entries, accounts, payees, balances, assets, and policies are synthetic. No real customer data, bank API, or brokerage service is used.
- The submission app's executable mixed bundle is one transfer plus one investment action. Other requests can stop as unsupported or unresolved; this is not general-purpose conversational banking.
- The investment catalog is intentionally bounded to DBS shares. Other securities, including UOB, are absent from the mock catalog; this says nothing about their real-world validity.
- Investment execution creates an inert order record. It has no market price, funding debit, cash settlement, or real trade.
- Business/risk controls use supplied synthetic policy, balances, history, and business day. Daily amount/count checks are not a production fraud, suitability, or market-risk system.

## AI and demonstration modes

- The prompt shield and registered-choice contract reduce injection risk; neither guarantees universal protection or semantic accuracy.
- Independent semantic validation is a separate source-based observer pass using the same configured Jev model in LIVE. It is not independent-model consensus or a deterministic proof of meaning.
- SCRIPTED DEMO provides canned answers for repeatable control-flow demonstrations. It does not measure LIVE accuracy or generalization.
- SCRIPTED is tuned to the documented scenarios and the `SGD 10` amount order. Variants such as `10 SGD`, or equal share-quantity and transfer-amount numbers, can remain unresolved or unsupported.
- Scenario C explicitly injects a validator discrepancy in SCRIPTED. It does not prove that LIVE inference detects that error.
- LIVE depends on the configured `typesafe/jev-1.13` model and OpenRouter Decisions availability. Provider errors do not fall back silently to SCRIPTED answers.

## Authorization and storage

- Identity and biometric verification are simulated. The **Simulate Biometric** button represents an explicit demo action and does not invoke a biometric SDK.
- Ed25519 signing is real cryptography with an ephemeral demo key, not a production customer credential or hardware-backed key.
- `SignedExecutionGateway` enforces the submission application's authorize/execute interface. The directly importable `MixedGateway` is in the same process and is not independently signature-aware or isolated by process/IAM controls.
- Bank/investment state, idempotency registries, keys, and audit records are process-local. Recreating the demo session, including Reset or loading a supported preset, discards that session's state. There is no durable database or distributed idempotency guarantee.
- The audit API is append-only and hash-linked, but storage is in memory. Chain verification is not external tamper-proof storage or a complete compliance record; the UI's simulated biometric/crypto status display is separate from backend audit events.
- This local hackathon prototype has no production authentication, multiuser isolation guarantee, deployment hardening, or production operational controls. All demos execute mock transactions only.
