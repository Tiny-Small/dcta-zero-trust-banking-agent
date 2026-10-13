# Security model

## Before confirmation

User text, provider data, entity names, and quoted/reference material are untrusted. The prompt shield scans before and during interpretation and keeps literal evidence in data fields, outside fixed instructions. The model receives registered choice questions and cannot supply free-form authorization or new trusted controls. A shield stop prevents downstream progression. This is defense in depth, not universal prompt-injection protection.

Ponder builds a versioned candidate graph; grounding resolves names against a synthetic directory and requires an explicit choice for ambiguity. A separate semantic observer compares the proposal and its bindings with source evidence. In LIVE it uses the same configured Jev model as interpretation: independence is a separate validation pass, not model/provider independence or guaranteed accuracy. Discrepancy, unresolved semantic evidence, or a contract error prevents an eligible review; a grounding ambiguity can proceed only through its explicit clarification path and fresh checks.

Deterministic business validation checks account ownership and usability, account/recipient status, currency, balance, limits, daily amount and operation-count policy, and the synthetic investment policy. Model output and displayed status cannot bypass the submission application's gates.

## Confirmation, signing, and execution

Confirmation is an exact human decision on the eligible review. It is separate from backend authorization. The demo then requires a simulated biometric action and a real Ed25519 signature over the review hash, confirmation hash, random nonce, and actor. The ephemeral private key is held by `DemoSigner`; `SignedExecutionGateway` is initialized with the public key only. The actor is synthetic and the biometric action does not authenticate a real person.

Before calling backend authorization, the gateway verifies the current review, accepted confirmation, biometric proof, signature, actor, and generation. Before every execution attempt, it rechecks the registered signed capability and current generation. Tampering, stale versions, rejection, or a V1→V2→V1 change do not revive old authority. Direct unsigned calls to the **submission gateway** are rejected.

The underlying `MixedGateway` remains directly importable, has no signature parameter, and runs in the same process. Its direct API is not protected by the signed adapter. This prototype does not claim process or IAM isolation against code running inside that process.

Successful mock execution commits the transfer and synthetic investment record together in process. Repeating the same current signed execution returns `ALREADY_EXECUTED` with the original receipt. The backend's append-only audit API records hash-linked lifecycle and execution events; chain verification checks retained records, not durable external history. UI text is HTML-escaped before rendering.

## Scope

Identity and biometric verification are simulated. Ed25519 operations are real, using an ephemeral demo key. Banking/investment state, idempotency registries, and audit storage are synthetic or process-local and reset when the demo session is recreated. There is no production authentication, bank/brokerage integration, durable audit database, hardware-backed customer key, or process/IAM isolation. See [limitations](LIMITATIONS.md).
