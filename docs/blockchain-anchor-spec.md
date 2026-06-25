# PopperPad Blockchain Anchor Specification

Status: design draft.

The blockchain anchor adapter records immutable commitments to PopperPad bundles
and falsification-market events. The chain is a timestamped settlement layer.
It does not store the full scientific record and does not decide whether claims
are true.

## Goals

- Anchor PopperPad bundle roots on one or more chains.
- Link on-chain events to off-chain content-addressed evidence.
- Support bounty escrow, bonds, challenge windows, and settlement events.
- Let readers verify anchors locally.
- Keep chain-specific code behind a common adapter interface.

## Non-goals

- No universal truth oracle.
- No requirement that all PopperPad users pay gas.
- No storage of large evidence blobs on-chain.
- No assumption that one chain is canonical.

## Chain Roles

Different chains can serve different roles:

- **Timestamp chain:** records manifest roots and publisher ids.
- **Escrow chain:** holds bounty funds and bonds.
- **Settlement chain:** emits payout and challenge events.
- **Governance chain:** manages market parameters.
- **Data chain:** stores blobs or durable data commitments.

The adapter should allow one chain to play several roles or several chains to
share the work.

## Anchor Object

```json
{
  "schema": "popperpad/chain/anchor/v1",
  "bundle_root": "sha256:...",
  "manifest_ref": "sha256:...",
  "storage_receipt_refs": ["sha256:..."],
  "publisher_ref": "did:example:alice",
  "previous_anchor_refs": ["sha256:..."],
  "purpose": "bundle_publication",
  "metadata": {
    "domain": "example",
    "pad_id": "example-pad"
  }
}
```

## Anchor Receipt

```json
{
  "schema": "popperpad/adapter/anchor-receipt/v1",
  "adapter": "evm",
  "chain_id": "eip155:1",
  "bundle_root": "sha256:...",
  "anchor_ref": "sha256:...",
  "storage_receipt_ref": "sha256:...",
  "tx_ref": "0x...",
  "block_ref": "0x...",
  "contract_ref": "0x...",
  "event_name": "PopperPadBundleAnchored",
  "finality": {
    "policy": "confirmations",
    "value": 64
  },
  "created_at": "2026-05-18T00:00:00Z"
}
```

## Minimal Contract Surface

The minimal contract only needs to emit events.

```text
anchorBundle(
  bytes32 bundleRoot,
  string storageUri,
  bytes32 storageReceiptHash,
  bytes32 previousAnchorHash,
  string publisherRef
)
```

Event:

```text
PopperPadBundleAnchored(
  bytes32 indexed bundleRoot,
  bytes32 indexed storageReceiptHash,
  bytes32 indexed previousAnchorHash,
  string storageUri,
  string publisherRef
)
```

This contract does not validate scientific claims. It only records commitments.

## Market Contract Surface

The falsification market needs separate contracts or modules.

### Bounty Registry

Responsibilities:

- register bounty commitment;
- bind bounty terms hash;
- bind claim ref and context ref;
- track deadline and challenge window;
- emit lifecycle events.

### Escrow

Responsibilities:

- hold bounty funds;
- hold submitter, attester, storage, and challenger bonds;
- release payouts;
- slash protocol-level misconduct.

### Challenge Manager

Responsibilities:

- accept challenges before the challenge deadline;
- bind challenges to PopperPad challenge refs;
- pause settlement while challenged;
- emit accepted, rejected, and resolved challenge events.

### Settlement

Responsibilities:

- execute predeclared payout rules;
- emit settlement events;
- prevent sponsor rug pulls after bounty opening;
- prevent payout before evidence commitment and challenge window completion.

## Event Commitments

Every value-moving event should reference a PopperPad object hash.

Examples:

- `bounty_ref`
- `submission_ref`
- `attestation_ref`
- `challenge_ref`
- `settlement_ref`
- `storage_receipt_ref`

If the event cannot be explained by a PopperPad object, it should not affect
scientific memory.

## Chain Families

### EVM Chains

Use EVM chains for first implementation because they have mature tooling for
escrow, events, and indexing.

Required adapter fields:

- `chain_id` as CAIP-2, for example `eip155:1`;
- contract address;
- transaction hash;
- block hash;
- event log index;
- finality policy.

### Cosmos SDK Chains

Use Cosmos chains when application-specific modules or interchain routing are
useful.

Required adapter fields:

- `chain_id`;
- transaction hash;
- event attributes;
- block height;
- finality policy;
- module name.

### Solana

Use Solana when low-cost high-volume commitments are needed.

Required adapter fields:

- cluster id;
- signature;
- slot;
- program id;
- account refs;
- finality commitment.

### Bitcoin and Timestamping Layers

Use Bitcoin or OpenTimestamps-style commitments when conservative timestamping
matters more than programmability.

Required adapter fields:

- transaction id or timestamp proof id;
- commitment path;
- block height;
- block hash where available;
- confirmation or timestamp policy.

### Substrate and Polkadot Ecosystem

Use Substrate chains when custom pallets, parachain logic, or app-specific
governance are useful.

Required adapter fields:

- chain id;
- extrinsic hash;
- block hash;
- pallet or contract id;
- event index;
- finality policy.

### Move-based Chains

Use Aptos, Sui, or other Move-based chains when resource-oriented settlement is
useful for bounty and bond objects.

Required adapter fields:

- chain id;
- transaction digest;
- package or module id;
- object refs;
- event refs;
- finality policy.

### Starknet and ZK-oriented Chains

Use Starknet or other proof-oriented chains for scalable commitments,
proof-adjacent markets, or compressed settlement records.

Required adapter fields:

- chain id;
- transaction hash;
- contract address;
- event keys;
- block hash or number;
- finality policy.

### Tezos

Use Tezos when its contract and governance environment fits a PopperPad
community.

Required adapter fields:

- chain id;
- operation hash;
- contract address;
- level;
- block hash;
- finality policy.

### Arweave

Use Arweave when permanent data publication is the main goal.

Required adapter fields:

- transaction id;
- data item id if using bundles;
- manifest root;
- content type;
- retrieval URI.

### Filecoin

Use Filecoin when storage deals and retrieval markets matter.

Required adapter fields:

- payload CID;
- deal id;
- provider id;
- duration;
- retrieval proof or test receipt.

### Data Availability Networks

Use Celestia-style, EigenDA-style, Avail-style, Ethereum blob, or other data
availability layers for high-volume publication where retrievability and
sampling properties are the main value.

Required adapter fields:

- network id;
- namespace or app id where applicable;
- blob id or commitment;
- block height;
- retrieval proof or sampling receipt;
- expiry or retention policy where applicable.

## Verification

To verify an anchor:

1. Fetch the anchor receipt.
2. Fetch the chain transaction and event.
3. Verify finality according to local policy.
4. Verify event fields match the receipt.
5. Fetch the storage receipt.
6. Fetch the bundle.
7. Recompute bundle root.
8. Verify `bundle_root` matches the chain event.
9. Apply local trust policy.

## Reorg and Finality Policy

The adapter must not hard-code one finality rule.

Examples:

- EVM proof-of-stake: finalized checkpoint or configurable confirmations.
- EVM L2: L2 finality plus optional L1 settlement confirmation.
- Solana: finalized commitment.
- Cosmos: block finality from consensus plus local light-client policy.
- Arweave: configurable confirmation depth.

Receipt status should support:

- `pending`;
- `finalized`;
- `reorged`;
- `conflicted`;
- `unknown`.

## Multi-chain Anchoring

High-value bundles can be anchored to several chains.

```json
{
  "schema": "popperpad/chain/multi-anchor/v1",
  "bundle_root": "sha256:...",
  "anchor_receipt_refs": ["sha256:...", "sha256:..."],
  "policy": {
    "required_finalized_anchors": 2,
    "accepted_chain_ids": ["eip155:1", "arweave:mainnet"]
  }
}
```

Multi-chain anchoring improves rewrite resistance, but it still does not decide
claim truth.

## Attack Queries

- Can a sponsor change bounty terms after escrow is funded?
- Can a payout occur without evidence availability?
- Can a chain reorg erase an anchor after import?
- Can the same submission be paid on multiple chains as if unique?
- Can a bridge or indexer fake an anchor receipt?
- Can governance change challenge windows after a bounty is open?
- Can a malicious adapter claim finality too early?

## MVP

The first chain anchor implementation should support:

- one EVM-compatible anchor contract;
- event-only bundle anchoring;
- local anchor verification;
- IPFS CID in the storage URI;
- no token requirement for anchoring or local verification;
- optional accepted-asset metadata for resource budgets;
- no automated payout.

The second implementation can add:

- escrow;
- bounty registration;
- challenge windows;
- settlement events;
- bonded storage receipts.

## Promotion Boundary

The chain adapter can claim:

- a bundle root was committed in a transaction;
- a transaction reached a configured finality threshold;
- an event links a chain commitment to a PopperPad bundle;
- escrow and settlement events followed contract rules.

The chain adapter cannot claim:

- the underlying science is correct;
- evidence is available unless storage verification passes;
- governance is uncapturable;
- token incentives are attack-resistant without separate modeling.
