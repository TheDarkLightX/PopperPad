# FCIS Completion Audit

Status: implementation preflight for the bounded market adapter.

Review endpoints:

- base: `8478691f41fb73bec9db50237527721659100118`
- audited candidate: `74aba021db2a3372f35f51856df447cb22af9100`
- change class: authority-bearing canonical boundary and bounded refinement

## Authority and artifact scope

The audited path is:

```text
canonical JSON bytes
  -> typed AdapterRequest
  -> profile and source binding checks
  -> bounded abstract market state
  -> authoritative pure market transition
  -> canonical AdapterResponse
```

The core owns admission, rejection precedence, explicit time inputs, state and
effect projection, and response commitments. The JSONL and profile loaders own
byte acquisition and source-file acquisition. They must not repair, discard, or
invent caller fields.

Files in the repair scope:

- `src/popperpad/refinement/finite_state.py`
- `src/popperpad/refinement/market_adapter.py`
- `src/popperpad/refinement/enumerator.py`
- `src/popperpad/refinement/profiles/market_single_slot_v1.py`
- `src/popperpad/shells/data_adapter_jsonl.py`
- their focused tests and package metadata

The existing market core, commit bundle, CAS log, and outbox remain unchanged.

## Construction, semantics, and failure model

- All request, response, state, command, binding, and manifest values that
  escape must be transitively immutable.
- Unknown fields at every mounted wire object are rejected. They are never
  normalized away before request hashing.
- The loaded profile hash must equal the binding's profile hash before any
  state is evaluated.
- A source binding is accepted only after every declared live source file
  matches its declared SHA-256 digest.
- Boundary failures return a typed `INVALID_INPUT` response bound to the input
  bytes. Invalid UTF-8, duplicate keys, floats, unknown fields, schema/version
  mismatch, and input-size violations retain distinct stable reason codes.
- Rejection has no successor effects or receipt. Accepted and
  committed-failure responses preserve the authoritative market effect-plan
  hash.
- JSONL acquisition is bounded before an entire hostile line is retained.

## Findings and failing witnesses

1. A canonical request, state, command, or execution context with an extra field
   is currently accepted after the field is silently discarded.
2. `apply_data_adapter(profile_b, binding_a, request_for_binding_a)` can evaluate
   profile B without first rejecting the binding mismatch.
3. `load_source_manifest` validates metadata relationships but does not compare
   the declared hashes with the live source bytes.
4. Float and non-finite JSON can escape the parser's typed error path, and the
   persistent shell reads an unbounded line before applying any size policy.
5. `EnumerationResult` is frozen only at the outer dataclass; its
   `reject_reasons` dictionary remains mutable.

## Evidence plan

- Add exact negative tests for all unknown-field levels and profile mismatch.
- Add live-source tamper and packaged-resource tests for the source manifest.
- Add float, non-finite, distinct error-code, raw-input commitment, and
  oversized-line recovery tests for the shell.
- Add retained-alias and getter-mutation tests for enumeration results.
- Run focused adapter/shell tests, the complete Python suite, and all Rust
  formatting, lint, and test gates.
- Regenerate the source manifest from the exact source commit after the source
  repair is committed, then verify the manifest against the checked-out bytes.

## Explicit nonclaims

This bounded refinement does not establish arbitrary-cardinality market
correctness, unbounded liveness or fairness, verifier semantic correctness,
hostile-recipe sandboxing, authenticated federation, datastore
linearizability, blockchain refinement, or release readiness for public
untrusted workloads. Those remain separate promotion gates.
