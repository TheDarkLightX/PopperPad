# PopperPad Decentralized Adapter Specification

Status: design draft.

This specification defines how PopperPad pads, evidence bundles, and market
objects can be published to decentralized storage and anchored on blockchains
without changing PopperPad's core rule:

> Truth is computed from evidence, context, recipes, and local trust policy.
> Chains and storage networks provide durability, timestamping, incentives, and
> immutability claims.

## Goals

- Make PopperPad objects portable across local pads, IPFS, Tau Net, EVM chains,
  appchains, and other immutable substrates.
- Keep the scientific record content-addressed and append-only.
- Let readers verify imported objects locally.
- Separate storage, anchoring, settlement, governance, and truth computation.
- Allow many backends without making PopperPad depend on one chain.

## Non-goals

- No chain-weighted scientific truth.
- No mutable global PopperPad database.
- No mandatory token for local scientific memory.
- No requirement that every PopperPad object be public.
- No assumption that all chains support the same semantics.

## Architecture

PopperPad decentralization has four planes.

### 1. Object Plane

The object plane contains PopperPad data:

- hypotheses;
- recipes;
- contexts;
- evidence;
- artifacts;
- market bounties;
- submissions;
- attestations;
- challenges;
- settlements;
- supersession edges.

Objects are serialized canonically and addressed by hash.

### 2. Storage Plane

The storage plane makes objects retrievable:

- local filesystem;
- Git;
- HTTP;
- S3-compatible object stores;
- IPFS;
- Filecoin;
- Arweave;
- chain-specific blob stores;
- other content-addressed networks.

Storage does not decide whether an object is valid. It only serves bytes.

### 3. Anchor Plane

The anchor plane records commitments:

- manifest roots;
- bundle roots;
- timestamps;
- publisher identities;
- chain transaction ids;
- storage CIDs or content ids;
- previous anchor links;
- bounty and settlement commitments.

Anchors make it hard to rewrite history, but they are not substitutes for local
verification.

### 4. Market Plane

The market plane handles escrow, bonds, slashing, rewards, and governance
parameters for the falsification market.

Market results become PopperPad metadata. They do not make a hypothesis true.

## Immutability Levels

PopperPad should describe immutability precisely.

| Level | Name | Meaning |
| --- | --- | --- |
| 0 | Local append-only | A local pad follows append-only discipline. |
| 1 | Content-addressed | Object bytes are bound to a hash. |
| 2 | Replicated | Multiple independent stores serve the same object. |
| 3 | Anchored | A chain or timestamp service records the object or manifest root. |
| 4 | Economically preserved | Storage nodes are paid or bonded to keep data available. |
| 5 | Governance protected | Protocol rules make deletion, mutation, or censorship costly. |

Most PopperPad workflows only need levels 0-3. Market-scale scientific memory
may need levels 4-5.

## Canonical Bundle

A decentralized adapter publishes a bundle, not a single loose file.

Bundle layout:

```text
bundle/
  manifest.json
  objects/
    sha256/
      ab/
        sha256-abcd....json
  blobs/
    sha256/
      ef/
        sha256-ef01....
  signatures/
    did-example-alice.sig
  indexes/
    refs.json
    graph.json
```

The bundle root is the canonical hash of `manifest.json`.

### Manifest

```json
{
  "schema": "popperpad/bundle/manifest/v1",
  "bundle_id": "example-bundle",
  "created_at": "2026-05-18T00:00:00Z",
  "producer": {
    "name": "PopperPad",
    "version": "0.1.0"
  },
  "root_hash": "sha256:...",
  "object_refs": ["sha256:..."],
  "blob_refs": ["sha256:..."],
  "entry_refs": ["sha256:..."],
  "previous_bundle_refs": ["sha256:..."],
  "signatures": [
    {
      "signer_ref": "did:example:alice",
      "signature_ref": "sha256:..."
    }
  ],
  "storage_hints": [],
  "anchor_hints": []
}
```

Rules:

- `root_hash` is computed after canonicalization.
- `object_refs` and `blob_refs` must be sorted.
- `entry_refs` identify the main objects a reader should inspect first.
- `previous_bundle_refs` create an append-only publication chain.
- `storage_hints` and `anchor_hints` are advisory and must be verified.

## Adapter Interface

Every decentralized adapter should implement the same logical interface.

```text
prepare(bundle) -> PreparedBundle
publish(prepared_bundle, backend_config) -> StorageReceipt
anchor(storage_receipt, anchor_config) -> AnchorReceipt
verify(storage_receipt | anchor_receipt) -> VerificationReport
import(storage_receipt | anchor_receipt, trust_policy) -> ImportReport
```

### PreparedBundle

```json
{
  "schema": "popperpad/adapter/prepared-bundle/v1",
  "manifest_ref": "sha256:...",
  "bundle_root": "sha256:...",
  "object_count": 12,
  "blob_count": 2,
  "byte_size": 123456,
  "canonicalization": "popperpad-json-c14n-v1"
}
```

### StorageReceipt

```json
{
  "schema": "popperpad/adapter/storage-receipt/v1",
  "adapter": "ipfs",
  "network": "ipfs-main",
  "bundle_root": "sha256:...",
  "content_id": "bafy...",
  "retrieval": {
    "kind": "cid",
    "value": "bafy..."
  },
  "created_at": "2026-05-18T00:00:00Z",
  "publisher_ref": "did:example:alice",
  "signature": "..."
}
```

### AnchorReceipt

```json
{
  "schema": "popperpad/adapter/anchor-receipt/v1",
  "adapter": "evm",
  "chain_id": "eip155:1",
  "bundle_root": "sha256:...",
  "storage_receipt_ref": "sha256:...",
  "tx_ref": "0x...",
  "block_ref": "0x...",
  "contract_ref": "0x...",
  "event_name": "PopperPadBundleAnchored",
  "created_at": "2026-05-18T00:00:00Z"
}
```

### VerificationReport

```json
{
  "schema": "popperpad/adapter/verification-report/v1",
  "target_ref": "sha256:...",
  "status": "pass",
  "checks": [
    {
      "name": "manifest_root",
      "status": "pass"
    },
    {
      "name": "object_hashes",
      "status": "pass"
    },
    {
      "name": "anchor_matches_bundle",
      "status": "pass"
    }
  ],
  "verified_at": "2026-05-18T00:00:00Z"
}
```

## Adapter Registry

Adapters should be registered by capability, not by hype.

```json
{
  "schema": "popperpad/adapter/registry-entry/v1",
  "adapter_id": "ipfs-cid-v1",
  "kind": "storage",
  "capabilities": {
    "content_addressed": true,
    "append_only": true,
    "native_timestamp": false,
    "native_payment": false,
    "native_governance": false,
    "smart_contracts": false
  },
  "trust_notes": [
    "CID integrity is strong.",
    "Availability depends on pinning or providers."
  ]
}
```

## Backend Classes

### Local Adapter

Use for development and private work.

Capabilities:

- canonical bundle export;
- local hash verification;
- local import;
- append-only pad checks.

### IPFS Adapter

Use for content-addressed distribution and public retrieval.

Capabilities:

- CID publication;
- CAR export;
- pinning receipts;
- gateway retrieval;
- local hash verification.

See [ipfs-adapter-spec.md](ipfs-adapter-spec.md).

### Chain Anchor Adapter

Use for timestamped immutable commitments and market settlement.

Capabilities:

- anchor manifest roots;
- record storage ids;
- bind publisher identities;
- emit settlement events;
- enforce escrow and challenge windows where supported.

See [blockchain-anchor-spec.md](blockchain-anchor-spec.md).

### Chain Adapter Matrix

Use for selecting the right immutable substrate by capability rather than by a
single preferred network.

Capabilities:

- classify timestamp, escrow, storage, data availability, and governance roles;
- define per-chain verification requirements;
- support multi-chain publication policies;
- keep scientific verification local even when several chains anchor the same
  bundle.

See [chain-adapter-matrix.md](chain-adapter-matrix.md).

### Tau Net Adapter

Use for specification-native publication, governance requirements, and logic-based
agreement/disagreement surfaces when Tau Net exposes a suitable integration path.

Capabilities:

- publish PopperPad adapter requirements as Tau Language specifications;
- anchor PopperPad manifests or manifest commitments;
- express governance constraints for falsification-market upgrades;
- map PopperPad claim/evidence relationships into Tau Net opinion or agreement
  surfaces where applicable.

See [tau-net-adapter-spec.md](tau-net-adapter-spec.md).

## Verification Pipeline

Readers must verify in this order:

1. Fetch bytes from the storage layer.
2. Recompute object and blob hashes.
3. Recompute manifest root.
4. Verify signatures.
5. Verify anchor receipts.
6. Verify chain finality according to local policy.
7. Run PopperPad schema checks.
8. Run recipe or evidence checks if the reader wants scientific status.
9. Apply local trust policy.

No adapter may skip local verification merely because a chain accepted a root.

## Attack Queries

Every adapter implementation should answer:

- Can a publisher anchor one root and serve different bytes?
- Can a storage node claim availability while refusing retrieval?
- Can an indexer point users to a stale or censored bundle?
- Can a chain reorg invalidate an anchor a user already trusted?
- Can a gateway rewrite or omit content?
- Can a malicious bundle include objects whose hashes do not match their refs?
- Can an adapter import unsigned objects into a trust policy that requires
  signatures?
- Can an attacker replay a valid old bundle as if it superseded a newer one?
- Can a market payout happen before the relevant evidence is retrievable?

## Minimum MVP

The first decentralized adapter release should include:

- canonical bundle manifest;
- local bundle export and import;
- IPFS CID publication;
- generic chain anchor receipt format;
- verification report format;
- README links and examples;
- no token requirement.

## Promotion Boundary

After the MVP, PopperPad can claim:

- bundles are content-addressed;
- adapter receipts can be verified locally;
- IPFS publication can distribute bundles by CID;
- chain anchors can commit to bundle roots.

PopperPad cannot yet claim:

- permanent availability;
- sybil resistance;
- censorship resistance across all adapters;
- validity of scientific claims;
- correctness of token incentives;
- support for every chain without a tested adapter.
