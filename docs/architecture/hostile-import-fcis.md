# Hostile Bundle Import FCIS Boundary

Status: implemented for bundle import v1.

## Authority flow

```text
hostile bundle directory
  -> bounded no-symlink file acquisition
  -> duplicate-key rejection and canonical manifest decoding
  -> exact refs, schemas, content hashes, and domain roots
  -> shell-authenticated bundle signatures and verifier receipts
  -> deeply immutable authentication, policy, provenance, and receipt values
  -> pure import-policy admission
  -> complete object/blob and truth-binding preflight
  -> one compare-and-swap CommitBundle publication
```

No pad mutation occurs before the complete preflight succeeds. CAS staging may
leave unreferenced bytes after an injected publication failure, but the
append-only log remains the single authority point and contains either the
whole import or none of it.

## Immutability claim

`@dataclass(frozen=True)` is not the immutability argument. Import authority
values also:

- inherit the `DeeplyImmutable` runtime guard;
- use slots and expose no writable instance dictionary;
- accept exact closed enums, bytes, tuples, `frozenset`, and `FrozenDict`
  children;
- copy and recursively freeze caller-owned JSON containers;
- validate the complete reachable graph at construction;
- reject mutable scalar subclasses and untrusted frozen dataclasses;
- have retained-alias and getter-mutation regression tests;
- are included in the repository-wide core dataclass and dependency gates.

This is executable runtime assurance for normal Python capabilities. It is not
a mathematical proof against hostile reflection or interpreter compromise.
Compiler-enforced Rust parity remains a separate repository-wide promotion
gate.

## Commitment domains

The import boundary assigns one meaning to each root:

| Root | Domain |
| --- | --- |
| content root | `bundle-content/v1` |
| signed manifest root | `bundle-manifest/v1` |
| unsigned signature target | `bundle-manifest-unsigned/v1` |
| bundle publisher key identifier | `bundle-import-signer-key/v1` |
| bundle signature statement | `bundle-import-signature/v1` |
| import policy root | `bundle-import-policy/v1` |
| verifier key identifier | `verifier-signer-key/v1` |
| verifier statement | `verifier-statement/v1` |
| verifier receipt | `verifier-receipt/v1` |

Object and blob CAS refs remain byte-content SHA-256 refs. A CAS ref is never
used as a substitute for one of the semantic roots above.

## Verifier receipt

`VerifierReceiptV1` is a canonical Ed25519 receipt. Its signed statement binds:

- the claim and optional context;
- the recipe, evidence object, and exact truth edge;
- sorted unique input and output roots;
- verifier key identity and version;
- the support or refutation result;
- the accepted verifier-policy and toolchain hashes.

The shell verifies the signature using an explicitly allowlisted key and
constructs an `AuthenticatedVerifierReceiptV1`. Pure admission then checks the
complete replay binding and every policy allowlist. A receipt for another edge,
evidence object, result, policy, version, or toolchain is rejected.

## Truth authority

Imports use one of two closed modes:

- `quarantined`: all imported truth and semantic edges are stored but excluded
  from the authority index, including after index rebuild or process restart;
- `trusted_receipt`: bundle signatures are required and every imported support
  or refutation edge must have exactly one authenticated, policy-admitted
  verifier receipt for each evidence ref.

A local replay creates a new locally committed evidence edge. It does not
retroactively mutate or bless the quarantined remote edge.

## Acceptance evidence

The executable suite covers:

- forged bundle and verifier signatures;
- unknown signer keys and signature algorithms;
- independent-root mismatch and signature thresholds;
- unaccepted storage adapters and missing required anchors;
- duplicate, unsorted, malformed, or out-of-domain refs;
- duplicate JSON keys, unknown manifest fields, noncanonical bytes, and
  symlink escape;
- per-file and cumulative byte bounds;
- invalid objects, publication failure injection, and zero partial authority;
- replay-binding mismatch;
- quarantine and trusted activation before and after restart;
- transitive immutability, retained aliases, getters, and the core graph gate.

## Nonclaims

The boundary assumes that `VerifiedImportProvenance` is constructed by an
adapter shell after successful storage or anchor verification. The bundle
directory is assumed not to be concurrently rewritten during an import. The
loader rejects observed symlinks and bounds every actual read, but does not
claim race-free directory traversal against a concurrent local writer. Key
revocation, key distribution, remote availability, chain finality policy,
OS-level recipe sandboxing, and Python-reflection resistance remain outside
this bounded claim.
