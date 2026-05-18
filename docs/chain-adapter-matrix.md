# PopperPad Chain Adapter Matrix

Status: design draft.

PopperPad should treat chains as adapter backends with different capabilities,
costs, finality assumptions, storage properties, and governance surfaces. No
single chain should be hard-coded as the source of scientific truth.

## Adapter Principle

Each chain adapter answers four questions:

- What can this network make immutable or timestamped?
- What can this network pay for or escrow?
- What can this network verify natively?
- What must PopperPad still verify locally?

The default answer to the last question is: scientific claims, evidence validity,
recipe execution, signatures, privacy policy, and local trust.

## Capability Classes

### Timestamp Anchors

Timestamp anchors record that a PopperPad bundle root existed at or before a
given chain event.

Useful backends:

- Bitcoin transactions or OpenTimestamps-style commitments;
- Ethereum or EVM event logs;
- Solana transactions;
- Cosmos events;
- Tezos operations;
- Substrate events;
- Tau Net anchors when available.

Best for:

- high-value publication checkpoints;
- preventing silent history rewrites;
- proving priority for bounties and submissions.

### Escrow and Settlement Chains

Escrow chains hold funds, bonds, and settlement logic.

Useful backends:

- EVM chains and L2s;
- Solana programs;
- Cosmos SDK modules;
- Substrate pallets;
- Move-based chains such as Aptos or Sui;
- Starknet contracts;
- other smart-contract platforms.

Best for:

- falsification bounties;
- challenge deposits;
- attester bonds;
- storage bonds;
- payout events.

### Permanent or Paid Storage Networks

Storage networks preserve bytes or storage deals.

Useful backends:

- IPFS with pinning;
- Filecoin;
- Arweave;
- Sia-like storage markets;
- chain-specific blob or data-availability layers.

Best for:

- evidence bundles;
- large artifacts;
- reproducibility logs;
- datasets where redistribution is allowed.

### Data Availability Layers

Data availability layers publish bytes or commitments so many verifiers can
retrieve them.

Useful backends:

- Celestia-style DA;
- EigenDA-style DA;
- Avail-style DA;
- Ethereum blob data where appropriate;
- appchain-native DA.

Best for:

- high-volume market events;
- rollup-style PopperPad settlement;
- short-to-medium-term public retrievability.

### Specification and Governance Networks

Specification networks help participants agree on requirements, policies, and
governance changes.

Useful backends:

- Tau Net;
- DAO governance systems;
- on-chain parameter registries;
- signed off-chain governance manifests anchored on-chain.

Best for:

- schema evolution;
- adapter capability acceptance;
- reward rule changes;
- non-truth governance constraints.

## Chain Profiles

### Bitcoin

Primary role:

- conservative timestamp anchor.

Use for:

- anchoring high-value bundle roots;
- priority proofs;
- long-lived checkpoint references.

Avoid using for:

- high-volume bounty settlement;
- large data storage;
- scientific adjudication.

Local verification still required:

- PopperPad bundle root;
- evidence validity;
- object signatures;
- storage availability.

### EVM Chains and L2s

Primary role:

- event anchoring, escrow, settlement, governance, token contracts.

Use for:

- first smart-contract MVP;
- bounty registry;
- escrow;
- challenge windows;
- settlement events;
- ERC-style token experiments if legally and operationally appropriate.

Risks:

- gas costs;
- bridge assumptions on L2s;
- governance capture;
- contract bugs.

### Solana

Primary role:

- low-cost high-throughput commitments and programmatic settlement.

Use for:

- many small attestations;
- frequent reproduction receipts;
- fast market interactions.

Risks:

- adapter complexity;
- different account model;
- finality policy must be explicit.

### Cosmos SDK Chains

Primary role:

- app-specific modules and interchain routing.

Use for:

- dedicated falsification-market modules;
- interchain settlement;
- sovereign community markets.

Risks:

- appchain operations burden;
- validator economics;
- bridge and IBC assumptions.

### Substrate and Polkadot Ecosystem

Primary role:

- custom pallets, parachain logic, or app-specific settlement.

Use for:

- custom PopperPad market pallets;
- domain-specific scientific communities;
- governance-heavy deployments.

Risks:

- chain-specific engineering cost;
- governance complexity;
- validator or parachain economics.

### Move-based Chains

Primary role:

- resource-oriented escrow and settlement.

Use for:

- strongly typed bounty and bond objects;
- explicit asset movement rules.

Risks:

- adapter maturity;
- smaller PopperPad-specific tooling base at launch.

### Starknet and ZK-oriented Chains

Primary role:

- scalable settlement and possible proof-friendly commitments.

Use for:

- high-volume attestations;
- proof-related markets;
- compressed verification records.

Risks:

- proving-system and bridge assumptions;
- contract/toolchain complexity.

### Arweave

Primary role:

- long-lived data publication.

Use for:

- public evidence bundles;
- archived manifests;
- durable indexes;
- final publication artifacts.

Risks:

- privacy mistakes are hard to undo;
- permanent publication is not suitable for sensitive data.

### Filecoin

Primary role:

- paid storage deals and retrieval markets.

Use for:

- large evidence archives;
- storage incentives;
- retrieval challenge integration.

Risks:

- deal lifecycle management;
- retrieval reliability must be measured, not assumed.

### IPFS

Primary role:

- content-addressed distribution.

Use for:

- CIDs for PopperPad bundles;
- CAR files;
- public sharing;
- gateway retrieval with verification.

Risks:

- availability depends on pinning or providers;
- mutable IPNS names must not replace immutable CIDs.

### Tau Net

Primary role:

- requirement publication, agreement surfaces, governance constraints, and
  future anchoring where available.

Use for:

- expressing PopperPad adapter policies;
- governance requirements;
- formal market rules;
- anchor receipts once stable integration exists.

Risks:

- adapter must track Tau Net's actual integration APIs;
- agreement surfaces must not be confused with scientific truth.

## Multi-chain Publication Policy

PopperPad should support publication policies like:

```json
{
  "schema": "popperpad/publication-policy/v1",
  "bundle_ref": "sha256:...",
  "storage": {
    "required": ["ipfs"],
    "optional": ["filecoin", "arweave"]
  },
  "anchors": {
    "required_finalized": 2,
    "accepted": ["bitcoin", "evm", "tau-net", "solana", "cosmos"]
  },
  "market": {
    "settlement_backend": "evm",
    "allow_cross_chain_receipts": true
  }
}
```

The policy is local. A user can require one anchor, several anchors, a specific
chain, or no chain at all.

## Adapter Selection

Use this default sequence:

1. Publish bundle to IPFS.
2. Pin or replicate bundle.
3. Anchor the bundle root on a low-friction smart-contract chain.
4. Anchor high-value checkpoints on Bitcoin or another conservative timestamp
   layer.
5. Publish permanent public artifacts to Arweave or Filecoin when privacy allows.
6. Use Tau Net for formal policy and governance agreement surfaces as the
   integration matures.
7. Add appchain or rollup infrastructure only after volume justifies it.

## Non-claims

Multi-chain anchoring does not prove:

- the claim is true;
- the evidence is meaningful;
- the recipe is fair;
- the tokenomics are safe;
- data is permanently available;
- all chains agree on the same governance.

It proves only what each adapter can verify: commitments, transactions,
receipts, availability observations, and settlement events.
