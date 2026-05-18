# PopperPad Tau Net Adapter Specification

Status: design draft.

This specification defines a conservative PopperPad adapter for Tau Net. Tau Net
is relevant because its public materials describe a blockchain and development
environment built around Tau Language, formal requirements, live consensus
detection, adaptive governance, and connections to external blockchains.

The PopperPad adapter should use those strengths for specification, governance,
and agreement surfaces. It should not ask Tau Net to decide scientific truth.

Sources consulted:

- https://www.tau.net/
- https://tau.net/tau-language/
- https://tau.net/tau-net/

## Goals

- Publish PopperPad bundle commitments into Tau Net when a stable integration
  surface is available.
- Express PopperPad market and adapter rules as Tau Language requirements where
  practical.
- Use Tau Net agreement/disagreement surfaces to expose which requirements,
  schemas, and governance changes participants accept.
- Connect PopperPad's falsification market to Tau Net without making token
  weight or governance decide claim truth.

## Non-goals

- No claim that Tau Net currently exposes a production PopperPad API.
- No dependence on Tau Net for local PopperPad verification.
- No Tau Net vote over whether a hypothesis is scientifically true.
- No publication of private evidence by default.

## Adapter Roles

The Tau Net adapter has three possible roles.

### 1. Specification Publisher

Publish adapter rules, schema constraints, market rules, and governance invariants
as Tau Language requirements.

Examples:

- "A bounty payout must reference a settlement object."
- "A settlement object must reference at least one evidence object."
- "Governance cannot mark a hypothesis as true."
- "A private-data flag must prevent network publication."

### 2. Bundle Anchor

Record PopperPad bundle roots, storage receipts, and publisher identities on Tau
Net when supported.

This mirrors the generic chain-anchor model:

- bundle root;
- storage URI or CID;
- publisher ref;
- previous anchor ref;
- purpose;
- timestamp or block reference.

### 3. Governance Agreement Surface

Use Tau Net's logic-oriented agreement model for protocol evolution:

- schema upgrades;
- accepted adapter capabilities;
- fee and bond constraints;
- privacy rules;
- reward eligibility rules;
- governance non-goals.

This should govern the market protocol, not scientific status.

## Tau Language Policy Boundary

Tau Language is appropriate for PopperPad policy surfaces where inputs can be
reduced to explicit boolean or symbolic facts.

Good policy targets:

- payout cannot happen before a challenge window closes;
- settlement requires evidence refs;
- storage receipt requires bundle root;
- private objects cannot be published by public adapters;
- governance cannot mutate historical objects;
- adapter imports fail closed if required signatures are absent.

Poor policy targets:

- deciding if a theorem is meaningful;
- deciding if an experiment generalizes;
- replacing recipe execution;
- ranking scientists globally;
- voting a claim into truth.

## Proposed Tau Policy Inputs

Host software should compute complex checks and pass simple facts into Tau.

Example facts:

```text
has_bounty_ref
has_submission_ref
has_evidence_ref
has_storage_receipt_ref
challenge_window_closed
has_open_challenge
bundle_root_matches
required_signatures_present
contains_private_data
publication_requested
governance_action_mutates_history
governance_action_marks_truth
```

Example outputs:

```text
allow_publish
allow_anchor
allow_settle
allow_import
deny_reason_private_data
deny_reason_missing_evidence
deny_reason_open_challenge
deny_reason_truth_vote
```

## Example Policy Intent

This is not final Tau syntax. It is the policy intent the implementation should
compile or encode using the current Tau toolchain.

```text
allow_publish iff
  publication_requested
  and not contains_private_data
  and bundle_root_matches
  and required_signatures_present

allow_settle iff
  has_bounty_ref
  and has_submission_ref
  and has_evidence_ref
  and has_storage_receipt_ref
  and challenge_window_closed
  and not has_open_challenge

deny governance action iff
  governance_action_mutates_history
  or governance_action_marks_truth
```

## Tau Net Anchor Receipt

```json
{
  "schema": "popperpad/adapter/anchor-receipt/v1",
  "adapter": "tau-net",
  "chain_id": "tau-net:main",
  "bundle_root": "sha256:...",
  "anchor_ref": "sha256:...",
  "storage_receipt_ref": "sha256:...",
  "tau_object_ref": "...",
  "block_ref": "...",
  "worldview_ref": "...",
  "agreement_ref": "...",
  "created_at": "2026-05-18T00:00:00Z"
}
```

Field notes:

- `tau_object_ref` is a placeholder until Tau Net exposes a stable object id.
- `worldview_ref` is optional and applies only to governance or agreement
  publication.
- `agreement_ref` is optional and should reference a requirement agreement, not
  a truth vote.

## Publication Flow

1. Build and verify a PopperPad bundle locally.
2. Publish the bundle to IPFS or another content-addressed storage layer.
3. Create a storage receipt.
4. Evaluate local Tau policy for publish or anchor permission.
5. Submit the bundle root and storage receipt commitment to Tau Net.
6. Record the Tau Net receipt as a PopperPad anchor receipt.
7. Verify the receipt locally before trusting it.

## Governance Flow

1. Draft a PopperPad protocol change as a requirement.
2. Encode the change as a Tau Language policy or requirement set.
3. Publish the requirement for Tau Net participants.
4. Detect agreement or disagreement through Tau Net surfaces where available.
5. If adopted, record a PopperPad governance object.
6. Link the governance object to schemas, adapters, or market parameters.
7. Preserve the previous rule and add a supersession edge.

## Privacy Rule

The Tau Net adapter must fail closed for private evidence.

```json
{
  "schema": "popperpad/adapter/privacy-policy/v1",
  "rule": "deny_publication_when_private_data_present",
  "inputs": {
    "contains_private_data": true,
    "publication_requested": true
  },
  "outputs": {
    "allow_publish": false
  }
}
```

Private data may still be represented by commitments, redacted artifacts, or
access-controlled storage, but public adapters must not leak raw private bytes.

## Attack Queries

- Can a Tau Net governance action mark a hypothesis true?
- Can private evidence be published because a local classifier failed open?
- Can an adapter anchor a bundle whose root does not match the storage receipt?
- Can a participant rewrite a PopperPad schema without a supersession record?
- Can a Tau Net agreement be misrepresented as scientific support?
- Can a market settlement occur while a valid challenge remains open?

## MVP

Do not start with full Tau Net integration.

First implement:

- Tau policy intent document;
- adapter capability registry entry;
- local fail-closed policy evaluator;
- placeholder Tau Net anchor receipt schema;
- IPFS-plus-chain publication path that Tau Net can later consume.

Then implement Tau Net integration when stable APIs or developer tooling are
available.

## Promotion Boundary

The Tau Net adapter can claim:

- PopperPad has a defined Tau Net integration boundary.
- PopperPad adapter rules can be expressed as formal policy targets.
- Tau Net anchors, when available, can be represented as PopperPad receipts.

The Tau Net adapter cannot yet claim:

- live Tau Net anchoring works;
- Tau Net can verify arbitrary PopperPad evidence;
- Tau Net governance establishes scientific truth;
- private data is safe without tested host-side classification and policy
  enforcement.

