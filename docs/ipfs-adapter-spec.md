# PopperPad IPFS Adapter Specification

Status: design draft.

The IPFS adapter publishes PopperPad bundles to a content-addressed storage
network. IPFS gives PopperPad strong content identity through CIDs, but it does
not by itself guarantee permanent availability. Availability requires pinning,
replication, Filecoin-style deals, paid storage, or independent mirrors.

## Goals

- Publish PopperPad bundles as immutable CIDs.
- Export bundles as CAR files for durable transfer.
- Verify fetched bytes against PopperPad hashes and CIDs.
- Record pinning and retrieval receipts as PopperPad evidence.
- Support later anchoring of CIDs on blockchains.

## Non-goals

- IPFS publication does not prove a claim true.
- IPFS publication does not guarantee availability forever.
- Gateway responses are not trusted without hash verification.
- Mutable IPNS or DNSLink names are discovery aids, not scientific records.

## Content Model

The adapter publishes the canonical PopperPad bundle from
[decentralized-adapter-spec.md](decentralized-adapter-spec.md).

Recommended encoding:

- CID version: CIDv1.
- Multibase: base32 for text display.
- Bundle package: CAR v1 or CAR v2.
- Object encoding: canonical JSON bytes.
- Blob encoding: original bytes with PopperPad hash metadata.
- Directory encoding: deterministic directory layout.

## Publication Flow

1. Build the PopperPad bundle.
2. Canonicalize `manifest.json`.
3. Verify every object hash.
4. Build a deterministic directory or DAG.
5. Add the bundle to IPFS.
6. Record the resulting CID.
7. Pin the CID locally or through providers.
8. Export a CAR file.
9. Create a `popperpad/adapter/storage-receipt/v1`.
10. Optionally anchor the receipt or CID on a chain.

## Retrieval Flow

1. Resolve CID from a storage receipt, gateway URL, or index.
2. Fetch the bytes.
3. Recompute the CID where tooling permits.
4. Recompute the PopperPad `bundle_root`.
5. Verify every object and blob hash.
6. Verify signatures.
7. Import into a local pad only after verification.

## Storage Receipt

```json
{
  "schema": "popperpad/adapter/storage-receipt/v1",
  "adapter": "ipfs",
  "network": "ipfs",
  "bundle_root": "sha256:...",
  "content_id": "bafy...",
  "retrieval": {
    "kind": "cid",
    "value": "bafy..."
  },
  "car_ref": "sha256:...",
  "pinning": [
    {
      "provider": "local-kubo",
      "status": "pinned",
      "observed_at": "2026-05-18T00:00:00Z"
    }
  ],
  "publisher_ref": "did:example:alice",
  "signature": "..."
}
```

## Pinning Receipt

```json
{
  "schema": "popperpad/adapter/ipfs-pinning-receipt/v1",
  "cid": "bafy...",
  "bundle_root": "sha256:...",
  "provider_ref": "did:example:storage-node-1",
  "pin_status": "pinned",
  "retrieval_test": {
    "status": "pass",
    "checked_at": "2026-05-18T00:00:00Z"
  },
  "signature": "..."
}
```

## Gateway Policy

Gateways are untrusted transport.

Valid gateway use:

- discovery;
- convenience downloads;
- browser retrieval;
- public preview.

Invalid gateway use:

- accepting content without hash verification;
- treating gateway availability as permanent preservation;
- using gateway URLs as canonical object ids.

## IPNS and DNSLink

Mutable names can point to the latest bundle, but they must not replace immutable
bundle CIDs.

Allowed:

- `popperpad.example` points to latest index CID;
- `ipns://...` points to latest pad manifest;
- README links use mutable names for convenience.

Required:

- every mutable name resolves to immutable bundle CIDs;
- imported scientific memory records the immutable CID and bundle root;
- supersession is represented with PopperPad edges, not by silently changing a
  mutable pointer.

## Availability Strategy

For MVP:

- local pin;
- at least one external pinning provider;
- CAR export checked into cold storage or object storage;
- retrieval smoke test before publishing a storage receipt.

For market scale:

- multiple independent pinning providers;
- storage-node bonds;
- retrieval challenges;
- paid replication rewards;
- optional Filecoin or Arweave publication for longer-term persistence.

## Attack Queries

- Can a gateway serve different bytes for the same URL?
- Can a publisher claim a CID but omit blobs from the bundle?
- Can a pinning provider claim to pin but fail retrieval?
- Can a mutable IPNS name hide refutations by pointing to an older index?
- Can a CAR export differ from the published CID?
- Can a bundle pass CID retrieval but fail PopperPad object verification?

## MVP Commands

Implementation should eventually expose commands with this shape:

```text
popperpad bundle export --pad ./pad --out ./bundle
popperpad adapter ipfs publish --bundle ./bundle --pin local
popperpad adapter ipfs verify --cid bafy...
popperpad adapter ipfs import --cid bafy... --pad ./pad
```

Command names are provisional. The important interface is the receipt and
verification behavior.

## Promotion Boundary

The IPFS adapter can claim:

- a bundle was published under a CID;
- fetched bytes match the CID;
- PopperPad object hashes match the manifest;
- pinning receipts record observed availability.

The IPFS adapter cannot claim:

- permanent storage;
- scientific truth;
- censorship resistance against all gateways;
- validity of market payout decisions.

