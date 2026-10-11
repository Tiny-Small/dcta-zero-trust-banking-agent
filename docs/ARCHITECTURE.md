# Architecture and trust boundaries

The UI submits text to `DemoSession`, which drives `MixedTextLifecycle`. The request follows this sequence:

```text
UNTRUSTED USER TEXT
  → prompt-injection shield
  → Parser+Jev candidate extraction and Ping scope/canonical decisions
  → Ponder intent assembly and mixed relation/action selection
  → synthetic directory grounding and explicit ambiguity resolution
  → independent semantic validation of the assembled meaning
  → deterministic business/risk validation
  → exact version-bound human confirmation
  → explicit simulated biometric step
  → Ed25519 sign-off of bundle, confirmation, nonce, and actor
  → SignedExecutionGateway public-key verification
  → backend authorization
  → atomic/idempotent mock transfer + simulated investment order
  → hash-linked in-memory audit
```

The model chooses only from registered, bounded options. Its output is evidence for a proposed interpretation, never confirmation, authorization, or execution authority. The semantic validator checks the assembled proposal separately; the deterministic gate applies account, recipient, asset, balance, transaction-limit, and velocity policy to synthetic state.

Grounding choices create a new revision and cause semantic and business checks to run again. Confirmation binds the exact eligible review. Simulated biometric verification, signature verification, authorization, and execution are distinct actions. A stale confirmation, signature, or authorization cannot be revived by returning to older text.

`SignedExecutionGateway` is the submission UI's authorize/execute boundary. It holds only the signer's public key and checks current review, confirmation, simulated biometric proof, Ed25519 signature, and signed capability before invoking the underlying `MixedGateway`. The signer and gateway run in the same demo process; the historical `MixedGateway` is an internal implementation component and is not process-isolated or itself signature-aware.

LIVE uses `DecisionsProvider` for configured Jev inference, wrapped by `GuardedProvider`, `RoleTargetTransport`, `ActionTargetTransport`, and `SemanticApplicabilityTransport`. SCRIPTED DEMO substitutes `ScriptedWireControl` at the provider boundary; it does not use saved hosted responses. Both modes continue through the same lifecycle gates and mock backend.
