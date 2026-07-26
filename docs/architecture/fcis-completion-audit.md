# FCIS Completion Audit

Status: completed repair audit for the bounded market adapter.

Review endpoints:

- base: `8478691f41fb73bec9db50237527721659100118`
- bound source revision: `c13d3052a4839ef2b4ec23e04a3f3e438dc99f3b`
- change class: authority-bearing canonical boundary and bounded refinement

## Authority and artifact scope

The audited path is:

```text
input bytes
  -> strict canonical decoder
      -> BoundaryFailureResponse when no valid request exists
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
- Failures before request construction return a committed
  `BoundaryFailureResponse` bound to the exact input bytes and local adapter
  binding, without a fabricated request identity. Failures after a valid
  request exists return a request-bound `AdapterResponse`. Invalid UTF-8,
  duplicate keys, floats, unknown fields, schema/version mismatch, and
  input-size violations retain distinct stable reason codes.
- Rejection has no successor effects or receipt. Accepted and
  committed-failure responses preserve the authoritative market effect-plan
  hash.
- JSONL acquisition is bounded before an entire hostile line is retained.

## Closed findings

1. Exact-field admission now rejects extra request, state, command, and
   execution-context fields instead of discarding them.
2. `apply_data_adapter` rejects profile/binding mismatch before state or command
   evaluation.
3. `load_source_manifest` verifies every declared digest against live source
   bytes in both source-checkout and installed-wheel layouts.
4. Float and non-finite JSON failures retain typed codes. The persistent shell
   bounds acquisition, responds to blank records, excludes JSONL delimiters
   from input commitments, drains an oversized line, and recovers for the next
   request.
5. `EnumerationResult` is frozen, slotted, deeply immutable, and stores reject
   reasons in `FrozenDict`.
6. Pre-request failures use a distinct committed response and never fabricate
   request IDs, state hashes, or request commitments.
7. Profile and source-manifest codec claims are closed to the canonical codec,
   and validation operations require a null command.
8. Enumeration reads every time representative from the supplied profile and
   aborts on any unexpected `INVALID_INPUT`, so an invalid corpus cannot be
   labeled complete.
9. Structural collection violations stop later semantic iteration, preserving
   the market transition's total rejection contract for malformed values.

## Completed evidence

- Exact negative tests cover unknown fields, profile mismatch, finite bounds,
  inapplicable command fields, codec mismatch, and operation shape.
- Tamper, missing-file, packaged-resource, and isolated-wheel checks cover the
  source manifest and runtime binding.
- Boundary tests cover invalid UTF-8, duplicate keys, floats, non-finite
  values, noncanonical encodings, blank records, framing-independent input-byte
  commitments, and oversized-line recovery.
- Profile-shift and malformed-collection regressions cover enumeration inputs
  and total-transition behavior.
- Retained-alias and getter-mutation tests cover enumeration immutability.
- The complete local Python suite passes: 398 tests.
- Rust formatting and strict clippy pass; all 13 Rust tests pass.
- A fresh wheel builds, contains both FCIS JSON resources, installs in an
  isolated environment, verifies every packaged source digest, and emits the
  pre-request boundary schema without request identity.
- GitHub CI passes on Python 3.10, Python 3.12, and the Rust kernel for the
  reviewed implementation head.

## Explicit nonclaims

This bounded refinement does not establish arbitrary-cardinality market
correctness, unbounded liveness or fairness, verifier semantic correctness,
hostile-recipe sandboxing, authenticated federation, datastore
linearizability, blockchain refinement, or release readiness for public
untrusted workloads. Those remain separate promotion gates.
