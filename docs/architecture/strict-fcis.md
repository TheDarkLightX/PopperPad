# Strict Functional Core / Imperative Shell Architecture

Status: accepted migration architecture.

## Decision

PopperPad treats values, not live service objects, as subsystem boundaries.
Directory names and `@dataclass(frozen=True)` are not sufficient. The assurance
claim requires all of the following properties together:

1. **Transitive immutability.** Every authority-relevant child reachable from a
   core value is immutable and owned by that value. A frozen record containing a
   `list`, `dict`, mutable `Mapping`, retained alias, cache, handle, or closure is
   not an immutable boundary.
2. **Pure, deterministic, total transitions.** Core outputs depend only on
   explicit state, command, policy, evidence, and version values. Expected
   failures are returned as `Reject`; authoritative failure transitions use the
   distinct `CommittedFailure` variant.
3. **Effects as exact values.** The core returns exact effect plans, receipt
   drafts, read/write footprints, and commit bundles. The shell must not
   reconstruct business semantics.
4. **Integer-only committed quantities.** Money, resource budgets, weights,
   durations, and protocol counters use integer atoms or explicitly encoded
   decimal/rational values. Binary floating point is not part of committed core
   state. The legacy `popperpad.canonical.canonical_json_bytes` surface remains
   byte-compatible with existing v1 pads, including their finite JSON floats;
   legacy float-bearing objects continue through v1 publication, while new FCIS
   commitments use the integer-only `popperpad.core.codec` surface.
5. **Canonical, domain-separated commitments.** The codec fixes versions, tags,
   normalization, ordering, and hash domains independently of Python object
   layout.
6. **Atomic compare-and-swap publication.** The shell binds an accepted plan to
   the exact pre-state root, writes one authoritative commit bundle, and delivers
   outbox effects idempotently.
7. **One-way dependencies.** Shell modules may import the core. Core modules may
   not import filesystem, process, clock, environment, randomness, network,
   database, adapter, UI, or orchestration authority.
8. **Executable architecture gates.** CI rejects forbidden imports, shallow
   immutable values, untyped mutable fields, nondeterministic canonical values,
   and parity drift.

## Target flow

```text
untrusted bytes / remote artifacts
  -> bounded canonical decode
  -> authenticated provenance values
  -> immutable Snapshot + Command + Policy + Evidence
  -> pure transition
       Reject
       | Accept(NextState, EffectPlan, ReceiptDraft, Footprint)
       | CommittedFailure(NextState, EffectPlan, ReceiptDraft, Footprint)
  -> shell verifies expected pre-root
  -> atomic CommitBundle publication
  -> idempotent outbox delivery
```

## Python and Rust

FCIS is a semantic architecture, not a language feature. Python is sufficient
for the product shell, local workflows, schemas, adapters, agent orchestration,
and an executable reference model. Python alone does not provide the strongest
construction boundary: callers can use reflection, fabricate nominal types, or
retain mutable objects unless every boundary copies and freezes them.

PopperPad therefore uses a two-language assurance plan:

- **Python** remains the reference semantics and high-level shell.
- **Rust** becomes the hardened portable kernel for canonical codecs, commitment
  roots, pure transition evaluation, verifier-receipt admission, and optionally
  sandbox workers or chain/WASM execution.
- Both implementations consume the same versioned vectors and must produce
  byte-identical decisions, rejections, roots, receipts, and effect plans.
- Rust is not permitted to invent a second semantic model. Promotion requires
  differential parity against the Python reference and independent vectors.

A Rust rewrite of the CLI, storage adapters, or UI is not required for FCIS.
Rust becomes necessary when PopperPad code is placed in a validator/appchain,
processes hostile network inputs at high volume, or is relied upon as a compact
trusted computing base.

## Migration stack

1. immutable value kernel, typed decisions, exact arithmetic, canonical v2, and
   dependency gates;
2. recipe execution split into pure planning/classification and a capability
   shell;
3. canonical commit bundles, typed receipts, compare-and-swap, outbox, and crash
   recovery;
4. pure bundle/import admission and atomic import;
5. Rust parity crate and golden vectors;
6. differential, mutation, alias, footprint, and failure-precedence promotion
   gates.

No migration PR may claim the entire architecture is complete merely because
its local tests pass. The promotion claim is generated from the gates above.
