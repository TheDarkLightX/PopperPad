# FCIS Completion Audit

Status: completed local repair audit for the bounded market adapter; hosted promotion is pending.

Review endpoints:

- base: `a297f376323808dc5acbc1e47d50bc607531c15e`
- bound source revision: `8c4ccb27d9ee4dd5a069a182167b47c1e00ad592`
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

- `src/popperpad/core/verifier.py` as a bound authority dependency
- `src/popperpad/refinement/finite_state.py`
- `src/popperpad/refinement/market_adapter.py`
- `src/popperpad/refinement/enumerator.py`
- `src/popperpad/refinement/profiles/market_single_slot_v1.py`
- `src/popperpad/shells/data_adapter_jsonl.py`
- their focused tests and package metadata

The authority-receipt market core and exact commit-publication changes are
inherited from current `main` through PR #21. This bounded repair adapts to that
authority boundary without further core mutation.

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
10. Settlement references are rejected in every phase except `SETTLED`,
    including terminal `EXPIRED` and `CANCELED` states.
11. JSONL draining treats only LF as the `readline` delimiter, so a CR at a
    bounded chunk edge cannot split one physical record into two requests.
12. The source-manifest loader validates the schema stored on disk instead of
    replacing it with a local constant.
13. Finite enumeration enforces `max_states` before admitting each new
    successor, so the advertised bound cannot be exceeded by one branching
    expansion.
14. Verifier-authority requests accept one exact caller-supplied Ed25519
    receipt in a separate immutable evidence envelope, derive its content
    reference from canonical bytes, and pass it to the market core for
    signature and exact-statement checks. The finite abstract command does not
    retain the receipt payload.
15. Enumeration derives deterministic mounted-model receipts from an explicit
    caller-supplied 32-byte Ed25519 fixture key, rejects keys outside the bound
    profile, and binds each receipt-bearing request into the corpus hash. No
    live receipt-provider callback participates in the search.
16. The source manifest binds the Ed25519 verifier implementation used by the
    market core, so signature-admission changes alter the binding hash.
17. Oversized-record hashing preserves a pending trailing CR across chunks and
    excludes it only when the next chunk begins with LF, making CRLF delimiter
    stripping independent of chunk placement.
18. JSON integer-decoder `ValueError` failures become committed typed boundary
    responses, so an adversarial integer literal cannot terminate the
    persistent JSONL shell.
19. The packaged shell exposes a module entry point over binary standard
    streams, making the audited adapter usable from an installed wheel.
20. Abstract state and command values retain only the profile-bounded
    semantic dimensions explored by the BFS. Authority evidence and concrete
    receipt identities stay outside that finite quotient; concretization uses
    the profile's declared model references.
21. Canonical JSON Unicode encoding failures become committed typed boundary
    responses, so lone surrogate escapes cannot terminate the persistent shell.

## Completed evidence

- Exact negative tests cover unknown fields, profile mismatch, finite bounds,
  inapplicable command fields, codec mismatch, and operation shape.
- Tamper, missing-file, packaged-resource, and isolated-wheel checks cover the
  source manifest and runtime binding.
- Boundary tests cover invalid UTF-8, duplicate keys, floats, non-finite
  values, noncanonical encodings, blank records, framing-independent input-byte
  commitments, and oversized-line recovery.
- Profile-shift, state-budget, and malformed-collection regressions cover
  enumeration inputs, resource bounds, and total-transition behavior.
- Missing-receipt, tampered-signature, unknown-field, embedded-evidence,
  wrong-key, and malformed-key regressions cover the verifier authority
  boundary and honest finite-search completeness.
- Terminal-state, chunk-boundary, and manifest-schema regressions cover the
  final fail-closed integrity cases.
- A split-CRLF chunk-edge regression proves the oversized input hash excludes
  both delimiter bytes and the shell recovers for the next request.
- A 5,000-digit integer regression proves decoder-limit failures remain
  committed to the input bytes and the following JSONL request still executes.
- A subprocess regression launches the documented module entry point, supplies
  a request over stdin, and validates its committed stdout response.
- Submission acceptance, committed verifier failure, and exhaustive bounded
  search regressions cover both authority outcomes without expanding abstract
  state or command values with receipt payloads or arbitrary receipt refs.
- A lone-surrogate regression proves unencodable JSON is committed to its input
  bytes and the following JSONL request still executes.
- Retained-alias and getter-mutation tests cover enumeration immutability.
- The complete local Python suite passes: 432 tests.
- Rust formatting and strict clippy pass; all 14 Rust tests pass.
- A fresh wheel builds, contains both FCIS JSON resources, installs in an
  isolated environment, verifies every packaged source digest, and emits the
  pre-request boundary schema without request identity.
- GitHub CI on Python 3.10, Python 3.12, and the Rust kernel must pass on
  this rebound head before merge.

## Explicit nonclaims

This bounded refinement does not establish arbitrary-cardinality market
correctness, unbounded liveness or fairness, verifier semantic correctness,
hostile-recipe sandboxing, authenticated federation, datastore
linearizability, blockchain refinement, exact concrete receipt-reference
trace preservation across the finite abstraction, or release readiness for
public untrusted workloads. Those remain separate promotion gates.

The packaged single-slot profile's accepted verifier reference is a public
model fixture. Its private key appears only in regression tests and supplies no
production trust. Deployments must bind their own accepted keys and external
receipt provider.
