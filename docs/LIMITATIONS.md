# Known limitations

- All directory entries, accounts, payees, balances, assets, and policies are synthetic. There is no real customer data or bank API.
- Identity and biometric verification are simulated. Ed25519 signing is real cryptography with an ephemeral demo key, not a production customer credential or hardware-backed key.
- Investment execution is a synthetic order record: no market price, cash settlement, brokerage, or real trade.
- Execution state, idempotency records, and hash-linked audit are process-local and reset on restart.
- The supported mixed-intent topology is bounded, principally a transfer plus one investment action. Other commands can stop as unsupported or unresolved.
- The prompt shield and bounded choice contract reduce injection risk but do not establish universal protection or model accuracy.
- SCRIPTED DEMO provides deterministic canned answers. It demonstrates control flow, not LIVE model quality or generalization.
- LIVE depends on the configured TypeSafe Jev model and OpenRouter availability. No real-provider accuracy claim follows from the scripted scenarios.
- `SignedExecutionGateway` protects the submission/demo interface. The underlying `MixedGateway` is in the same process and is not independently signature-aware or process-isolated.
- This prototype has no production authentication, durable audit database, banking API, brokerage connection, voice/TRTC interface, or production operational controls.
