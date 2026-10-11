# Security model

## Before confirmation

User text, provider data, entity names, and quoted/reference material are untrusted. The prompt shield scans before and during interpretation and keeps literal evidence in data fields, outside fixed instructions. The model receives registered choice questions and cannot supply free-form authorization or new trusted controls. A shield stop prevents downstream progression. This is defense in depth, not a universal prompt-injection guarantee.

Ponder builds a versioned candidate graph; grounding resolves names against a synthetic directory. An independent semantic validator compares the proposal with source meaning. Discrepancy or unresolved meaning freezes or clarifies the request. Deterministic business validation then checks ownership, active accounts and recipients, balance, limits, velocity, and the synthetic investment policy. Neither model response nor a displayed status can bypass those gates.

## Confirmation, signing, and execution

Confirmation is an exact human decision on the eligible review. It is separate from backend authorization. The demo then requires a simulated biometric action and an Ed25519 signature over the review hash, confirmation hash, random nonce, and actor. The ephemeral private key stays with `DemoSigner`; `SignedExecutionGateway` is initialized with the public key only.

Before calling backend authorization, the gateway verifies the current review, accepted confirmation, biometric proof, signature, actor, and generation. Before every execution attempt, it rechecks the registered signed capability and current generation. Tampering, stale versions, rejection, or a V1→V2→V1 change do not revive old authority. Direct unsigned calls to the **submission gateway** are rejected. The underlying historical `MixedGateway` has no signature parameter and is not a separate process security boundary.

Successful mock execution commits the transfer and synthetic investment record together in process. Repeating the same signed execution returns `ALREADY_EXECUTED` with the original receipt. The backend keeps a hash-linked in-memory audit of lifecycle and execution events. UI text is HTML-escaped before rendering; user-provided strings cannot render as trusted status controls.

## Scope

Identity, biometric verification, bank state, investment order, key management, persistence, and audit storage are simulated or process-local. There is no production authentication, bank integration, brokerage integration, hardware-backed key, or process isolation. See [limitations](LIMITATIONS.md).
