# PopperPad Verifiable Epistemic Artifact Market

Status: design draft.

This document turns PopperPad's "scientific memory" model into a decentralized
market design. The market rewards people and agents for making claims testable,
constructing proofs, finding counterexamples, reproducing checks, preserving
evidence, improving verifiers, and maintaining the machinery that lets others
verify results.

The central rule is simple:

> The market cannot decide truth by payment or vote. It can buy proof,
> refutation, reproduction, and replayable evidence whose verification computes
> scientific status.

Truth is not token-weighted; truth certificates are token-funded. Stake can fund
search, proof construction, reproduction, and preservation, but only a
replayable verifier-accepted certificate can change claim status.

The chain records commitments, escrows, challenges, attestations, and payout
events. Verifiers decide scoped check results. PopperPad stores the resulting
certificates and evidence.

## Thesis

Most knowledge systems overpay novelty and underpay correction. PopperPad should
do the opposite: make it economically attractive to find the exact place where a
claim breaks.

A verifiable epistemic artifact market rewards:

- precise hypotheses;
- reproducible test recipes;
- proofs;
- counterexamples;
- independent reproduction;
- formalizations;
- verifier improvements;
- preserved artifacts;
- schema and harness maintenance;
- evidence that narrows a claim's valid scope.

The goal is to buy verifiable epistemic deltas: proof when a claim can be shown,
refutation when it breaks, reproduction when evidence needs confirmation, and
boundary discovery when a broad claim can be turned into scoped truth.

## Non-negotiable Design Rules

- **Truth is not token-weighted; truth certificates are token-funded.** Stake
  can fund search, proof, reproduction, and preservation, but it cannot make a
  claim supported without verifier-accepted evidence.
- **Proofs are first-class output.** A proof accepted by a declared verifier is
  a valuable sellable artifact.
- **Refutations are first-class output.** A counterexample is not a failure of
  the system. It is one of the system's most valuable products.
- **Evidence is append-only.** New evidence supersedes or contextualizes old
  evidence; it does not erase it.
- **Local verification wins.** Any user should be able to recompute the status
  of a claim from the objects they trust.
- **The chain stores commitments, not bulky science.** Large artifacts, datasets,
  traces, and logs live in content-addressed storage.
- **Governance controls market parameters, not scientific conclusions.**

## Game Surface

### Players

- **Claim author:** publishes a testable PopperPad hypothesis.
- **Sponsor:** funds a bounty for refutation, reproduction, or maintenance.
- **Refuter:** submits a counterexample or evidence that breaks a hypothesis
  under its stated context.
- **Reproducer:** reruns a recipe and signs the resulting evidence.
- **Recipe maintainer:** keeps tests, harnesses, adapters, and toolchain recipes
  working as dependencies change.
- **Storage node:** preserves blobs, artifacts, traces, and evidence bundles.
- **Indexer:** makes claims and evidence discoverable.
- **Challenger:** disputes malformed, unavailable, duplicate, or fraudulent
  evidence.
- **Curator:** builds useful trust lists, topic indexes, and review sets.
- **Governance participant:** votes on protocol parameters, schema acceptance,
  emissions, and treasury grants.

### Actions

- Register a claim commitment.
- Attach a PopperPad hypothesis, recipe, context, and artifact bundle.
- Open a bounty.
- Submit a refutation bundle.
- Submit a reproduction bundle.
- Sign an attestation.
- Challenge a submission.
- Mirror artifacts.
- Index claims and evidence.
- Settle a bounty payout.
- Slash a bonded actor for protocol-level fraud or unavailable data.

### Information Sets

Public:

- claim hash;
- bounty terms;
- relevant PopperPad object refs;
- recipe refs;
- context refs;
- evidence bundle roots;
- signatures;
- settlement events;
- challenge outcomes.

Local or optional:

- private notes;
- unpublished failed attempts;
- local trust policies;
- private datasets that cannot be redistributed;
- private identity mappings.

### Timing

1. Claim author publishes a PopperPad hypothesis.
2. Sponsor opens a bounty with explicit scope and payout terms.
3. Refuters submit evidence bundles before the bounty deadline.
4. Reproducers independently rerun the relevant recipe or inspect the artifact.
5. A challenge window opens.
6. Valid challenges block, slash, or reduce payout.
7. If the challenge window closes cleanly, the market settles payout.
8. PopperPad records the settlement as evidence metadata, not as truth.

### State

Each market item should track:

- `claim_ref`: PopperPad hypothesis hash.
- `recipe_refs`: accepted check recipes.
- `context_ref`: the context in which the bounty applies.
- `bounty_pool`: available payout.
- `sponsor_ref`: identity or account funding the bounty.
- `submission_refs`: submitted evidence bundle refs.
- `attestation_refs`: reproduction or review attestations.
- `challenge_refs`: dispute objects.
- `storage_refs`: artifact availability commitments.
- `status`: open, submitted, challenged, payable, settled, expired, canceled.

### Payoff

The market should distinguish three forms of stake:

- **Bounty escrow:** reward pool for useful scientific work.
- **Anti-spam bond:** small bond posted by claim authors, submitters, attesters,
  indexers, or storage nodes to discourage malformed work.
- **Confidence stake:** optional speculative stake that a claim will survive a
  particular refutation window.

Do not automatically punish a claim author because a claim is refuted. Honest
refutation is the point. Slash only for protocol-level bad behavior, such as
unavailable evidence, fake attestations, invalid commitments, or deceptive
scope changes.

## Attack Queries

The core mechanism should be tested against these profitable-deviation queries:

- Can a refuter get paid with a fake counterexample?
- Can an attester get paid without rerunning the recipe?
- Can a sponsor bait refuters with ambiguous scope and then deny payout?
- Can a claim author change the claim after a bounty is opened?
- Can a cartel of attesters rubber-stamp each other's submissions?
- Can an indexer hide refutations while still earning rewards?
- Can storage nodes claim availability while withholding data?
- Can a submitter replay an old counterexample as if it were new?
- Can a high-stake actor make a false claim look supported by buying votes?
- Can governance redefine reward rules after work has been submitted?

Every production mechanism should answer these queries with either a deterministic
guard, an economic bound, or an explicit non-claim.

## Bounded Economic Model

Use the following first-pass inequality for any role that can extract value by
lying:

```text
DefectGain <= DetectionProbability * SlashAmount + FutureValueLost
```

For deterministic protocol facts where bad behavior is detected before payout:

```text
DefectGain <= SlashAmount + FutureValueLost
```

Concrete variables:

- `B`: bounty pool.
- `R`: reward paid to a submitter or attester.
- `D`: submitter bond.
- `A`: attester bond.
- `S`: storage bond.
- `C`: cost of honest work.
- `G`: gain from fraudulent payout.
- `p`: probability fraud is detected during the challenge window.
- `F`: future value lost through reputation, deny lists, or reduced eligibility.

Minimum condition for fake evidence to be irrational:

```text
G <= p * D + F
```

Minimum condition for fake attestation to be irrational:

```text
R <= p * A + F
```

Minimum condition for fake storage claims to be irrational:

```text
StorageReward <= p * S + F
```

These are not final tokenomics. They are the checks the tokenomics must satisfy.

## Market Types

### Counterexample Bounty

Pays for evidence that breaks a hypothesis under the stated context.

Required objects:

- hypothesis ref;
- recipe ref or formal falsification condition;
- context ref;
- bounty terms;
- submission bond;
- challenge window;
- payout rule.

Useful for claims like:

- "This parser accepts exactly this grammar."
- "This invariant holds for all transitions in this bounded model."
- "This optimization preserves output for this input domain."
- "This proof tactic never increases goal count under this theorem class."

### Reproduction Bounty

Pays independent actors to rerun checks and publish signed results.

This rewards support, refutation, and skipped results differently:

- `PASS`: paid if the recipe ran and matched expected output.
- `FAIL`: paid more if the failure is new and well packaged.
- `SKIP`: paid little or not at all unless the skip reveals a useful missing
  dependency, portability issue, or documentation failure.

### Boundary Bounty

Pays for narrowing a broad claim into a sharper claim with explicit assumptions.

This is important because many "false" claims become useful after their real
boundary is found.

Example output:

- original claim ref;
- counterexample ref;
- new scoped hypothesis ref;
- supersedes or narrows edge;
- explanation of excluded cases.

### Recipe Maintenance Bounty

Pays maintainers to keep old checks alive across toolchain, dependency, compiler,
dataset, and hardware changes.

This prevents scientific memory from decaying into dead links and unreplayable
scripts.

### Artifact Availability Bounty

Pays storage nodes for preserving content-addressed blobs and evidence bundles.

Storage rewards should require:

- content hash;
- availability proof or retrieval challenge;
- minimum replication target;
- storage duration;
- slashable availability bond.

### Curation Bounty

Pays for useful indexes, trust lists, topic maps, duplicate detection, and claim
clusters.

Curation rewards should be separated from truth. A curator can say "these claims
belong together" or "this evidence is widely reproduced"; they cannot make a
claim true by ranking it highly.

## Protocol Objects

PopperPad can represent the market with append-only JSON objects.

### Bounty

```json
{
  "schema": "popperpad/market/bounty/v1",
  "bounty_id": "example-proof-bounty",
  "market_type": "proof",
  "claim_ref": "sha256:...",
  "accepted_verifier_refs": ["sha256:..."],
  "accepted_recipe_refs": ["sha256:..."],
  "context_ref": "sha256:...",
  "terms": {
    "deadline": "2026-12-31T23:59:59Z",
    "challenge_window_seconds": 604800,
    "max_payout": "1000 PPAD",
    "payout_condition": "verifier_passes",
    "duplicate_policy": "first_valid_or_best_explained"
  },
  "settlement_ref": null
}
```

Proof bounties pay when:

```text
Check(claim, certificate, context) = PASS
```

Counterexample bounties pay when:

```text
Run(counterexample, recipe, context) = FAILS_CLAIM
```

### Truth Certificate

```json
{
  "schema": "popperpad/certificate/truth/v1",
  "certificate_id": "lean-proof-cert-001",
  "certificate_kind": "proof",
  "claim_ref": "sha256:...",
  "context_ref": "sha256:...",
  "verifier_ref": "sha256:...",
  "recipe_ref": "sha256:...",
  "evidence_refs": ["sha256:..."],
  "artifact_refs": ["sha256:..."],
  "verifier_result": {
    "accepted": true,
    "status": "supported"
  },
  "signatures": ["did:example:prover#sig"],
  "truth_boundary": "verifier_checked_certificate"
}
```

This is the sellable object. Payment funds its production; verifier acceptance
makes it eligible for payout; PopperPad stores it as scientific memory.

### Submission

```json
{
  "schema": "popperpad/market/submission/v1",
  "bounty_ref": "sha256:...",
  "submitter_ref": "did:example:...",
  "evidence_refs": ["sha256:..."],
  "artifact_refs": ["sha256:..."],
  "claim": {
    "kind": "refutation",
    "summary": "Counterexample input violates the stated invariant."
  }
}
```

### Attestation

```json
{
  "schema": "popperpad/attestation/v1",
  "subject_ref": "sha256:...",
  "attester_ref": "did:example:...",
  "attestation_type": "reproduced",
  "context_ref": "sha256:...",
  "result_ref": "sha256:...",
  "signature": "..."
}
```

### Challenge

```json
{
  "schema": "popperpad/market/challenge/v1",
  "submission_ref": "sha256:...",
  "challenger_ref": "did:example:...",
  "challenge_type": "unavailable_artifact",
  "evidence_refs": ["sha256:..."]
}
```

### Settlement

```json
{
  "schema": "popperpad/market/settlement/v1",
  "bounty_ref": "sha256:...",
  "winning_submission_refs": ["sha256:..."],
  "payouts": [
    {
      "recipient_ref": "did:example:...",
      "amount": "700 PPAD",
      "reason": "valid_counterexample"
    }
  ],
  "settlement_tx": "chain:..."
}
```

## Blockchain Architecture

The blockchain should be a settlement and commitment layer, not the scientific
database.

The detailed adapter specifications are:

- [decentralized-adapter-spec.md](decentralized-adapter-spec.md)
- [ipfs-adapter-spec.md](ipfs-adapter-spec.md)
- [blockchain-anchor-spec.md](blockchain-anchor-spec.md)
- [chain-adapter-matrix.md](chain-adapter-matrix.md)
- [tau-net-adapter-spec.md](tau-net-adapter-spec.md)

### Off-chain

Off-chain systems hold:

- PopperPad objects;
- evidence logs;
- datasets;
- build artifacts;
- traces;
- proofs;
- signatures;
- local trust policies;
- indexes and search data.

These objects are content-addressed and can be mirrored through Git, HTTP, S3,
IPFS-like networks, or other storage layers.

### On-chain

On-chain contracts hold:

- bounty escrows;
- token balances;
- object commitments;
- evidence bundle roots;
- deadline and challenge windows;
- payout rules;
- bonds and slashing rules;
- settlement events;
- governance parameters.

The chain should never need to understand the full scientific object. It only
needs enough information to enforce market rules around commitments and payout.

### Consensus Boundary

The chain can say:

- this bounty existed;
- this commitment was submitted before this deadline;
- this challenge was filed in time;
- this payout was made;
- this bond was slashed under the protocol rules.

The chain should not say:

- this claim is true;
- this paper is correct;
- this theorem is meaningful;
- this agent is scientifically trustworthy in all contexts.

## Decentralization Roadmap

### Phase 0: Token-fueled local market objects

Build the market with signed PopperPad objects, explicit resource budgets, and
external settlement assets such as Agoras, stablecoins, USD rails, grants, or
manual settlement. The network should be token-fueled immediately, but not by a
truth-token.

Deliverables:

- bounty, submission, attestation, challenge, and settlement schemas;
- resource-budget schemas for compute, storage, model calls, verifier runs, and
  retrieval;
- local `doctor` checks for market objects;
- duplicate detection by content hash and claim scope;
- signed attestations;
- import and export of complete evidence bundles.

Exit criteria:

- users can open a bounty;
- contributors can earn credits through useful work before buying credits;
- another user can submit a counterexample;
- independent users can attest reproduction;
- the final settlement is recorded as append-only evidence.

### Phase 1: Decentralized storage and signatures

Add real replication with explicit storage credits, retrieval challenges, and
slashable availability commitments.

Deliverables:

- pad mirroring;
- artifact pinning;
- resource-budget manifests;
- signed manifests;
- remote subscription;
- local trust policy files;
- retrieval checks.

Exit criteria:

- a user can verify a remote bounty and evidence bundle without trusting the
  index that found it.

### Phase 2: Smart-contract escrow

Move bounty escrow, bonds, deadlines, and settlement events on-chain.

Recommended starting shape:

- one bounty registry contract;
- one escrow contract;
- one bond manager;
- one settlement contract;
- off-chain evidence bundles referenced by content hash.

Avoid building an appchain here unless throughput or fee pressure proves it is
needed.

Exit criteria:

- bounty funds cannot be rugged by the sponsor;
- submissions are timestamped by commitment;
- payouts follow predeclared rules;
- challenge windows are enforced.

### Phase 3: Attestation network

Reward independent reproduction and challenge work.

Deliverables:

- attester registration;
- bonded attestations;
- random or market-selected reproduction assignments;
- challenge deposits;
- slashing for fake, unavailable, or non-reproducible attestations;
- attester deny lists or local trust profiles.

Exit criteria:

- fake attestation has negative expected value under the bounded model;
- honest reproduction is paid enough to cover expected cost.

### Phase 4: Native PPAD token

Introduce a native PopperPad token only after the Agoras/external-asset plus
PPAD-credit market has evidence of real demand.

The native token should pay for:

- bounty creation;
- submitter and attester bonds;
- storage and indexing rewards;
- model/API reimbursements;
- agent compute budgets;
- reproduction rewards;
- recipe maintenance;
- governance participation over protocol parameters.

The native token should not:

- vote claims true;
- buy scientific status;
- replace local verification;
- reward pure popularity.

### Phase 5: Federation or appchain

Consider a dedicated network only if the settlement layer becomes the bottleneck.

Reasons to consider it:

- high volume of small bounties;
- specialized storage proofs;
- low-fee reproduction attestations;
- protocol-native identity and reputation;
- application-specific dispute windows.

Reasons not to:

- the market is still small;
- off-chain settlement works;
- storage and indexing are the real bottlenecks;
- governance is not mature.

## Tokenomics Draft

Token name used below: `PPAD`. This is a placeholder design name for a possible
future native token. Before PPAD exists, PopperPad can use Agoras, stablecoins,
USD rails, donations, grants, and non-transferable PPAD credits.

### Token Utility

Accepted fuel assets and credits are used for:

- bounty funding;
- submitter bonds;
- attester bonds;
- storage bonds;
- challenge deposits;
- model/API reimbursements;
- agent compute budgets;
- proof construction rewards;
- truth certificate rewards;
- recipe maintenance rewards;
- indexer fees;
- governance over protocol parameters;
- treasury grants for public-good reproduction work.

### Token Non-utility

Fuel assets, credits, or native PPAD are not used for:

- deciding truth;
- overriding evidence;
- forcing users to trust a claim;
- censoring local pads;
- mutating historical records.

### Reward Classes

High priority:

- verifier-accepted proofs;
- novel counterexamples;
- independent reproduction of important claims;
- useful formalizations;
- verifier improvements;
- preservation of high-value evidence bundles;
- maintenance of widely used recipes;
- discovery of scope boundaries.

Medium priority:

- indexing;
- duplicate clustering;
- metadata cleanup;
- topic maps;
- schema migration support.

Low or no priority:

- raw claim posting;
- popularity votes;
- duplicate attestations;
- low-context opinions;
- unverifiable summaries.

### Draft Allocation

These are planning numbers, not a launch recommendation:

- 40% scientific rewards and emissions;
- 20% ecosystem treasury;
- 20% core contributors, vested long term;
- 10% public/community distribution;
- 5% storage and indexer bootstrap;
- 5% liquidity, market operations, and emergency reserves.

Before any live token, this should be reviewed for legal, tax, governance, and
market-manipulation risk.

### Emission Policy

Emissions should be work-weighted, not time-only.

Reward budgets can be allocated by epoch across:

- counterexample bounties;
- reproduction bounties;
- storage availability;
- recipe maintenance;
- curation and indexing;
- security challenges.

Emission should decay as external bounty demand grows. The long-term market
should be funded mainly by sponsors who want claims tested and by users who want
evidence preserved.

### Fees and Sinks

Possible sinks:

- bounty creation fee;
- settlement fee;
- challenge fee;
- storage subscription fee;
- indexer listing fee;
- burned fraction of slashed bonds;
- treasury fraction of protocol fees.

Keep fees low enough that small scientific claims can still be tested.

### Slashing

Slash only protocol-level misconduct:

- fake attestation;
- unavailable artifact after claiming storage;
- malformed commitment;
- duplicate submission presented as novel;
- invalid signature;
- scope mutation after bounty opening;
- censorship or non-service by bonded indexers when they have committed to
  serve a result set.

Do not slash for being honestly wrong.

## Payout Rules

### Counterexample Payout

A counterexample submission becomes payable when:

1. It was submitted before the deadline.
2. It references the exact bounty and claim.
3. Required artifacts are available.
4. Required recipes run or the submission includes an accepted formal witness.
5. The evidence contradicts the claim under the bounty context.
6. The challenge window closes without a successful challenge.

If multiple valid submissions arrive:

- pay the first valid submission for priority;
- reserve a smaller reward for independent confirmation;
- optionally pay a better-minimized counterexample if it materially improves
  clarity.

### Reproduction Payout

A reproduction submission becomes payable when:

1. It uses an accepted recipe or declares a compatible reproduction recipe.
2. It records the toolchain and context.
3. It includes logs and artifacts.
4. It is signed by the reproducer.
5. It survives the challenge window.

Failures should be paid more than passes when they are novel and actionable.

### Maintenance Payout

A recipe maintenance submission becomes payable when:

1. It updates a recipe without changing the claim semantics.
2. It preserves or improves replayability.
3. It links old and new recipes with a supersession edge.
4. It passes deterministic checks.
5. It survives review or challenge.

## Governance

Governance can control:

- fee rates;
- bond minimums;
- challenge window durations;
- accepted schema versions;
- treasury grants;
- reward epoch budgets;
- storage-market parameters;
- indexer-service requirements.

Governance cannot control:

- whether a claim is true;
- whether a user must trust an attester;
- whether local evidence can exist;
- whether a valid historical object can be erased.

## Reputation

Reputation should be evidence-derived and locally interpretable.

Useful reputation inputs:

- number of reproduced submissions;
- number of successful challenges;
- number of failed challenges;
- artifact availability history;
- recipe maintenance history;
- domains of competence;
- identity signatures from trusted parties.

Avoid global opaque scores. A theorem-proving attester and a genomics-data
attester should not share one meaningless rank.

## Minimal MVP

Build this before any chain:

- `popperpad/market/bounty/v1`;
- `popperpad/market/submission/v1`;
- `popperpad/attestation/v1`;
- `popperpad/market/challenge/v1`;
- `popperpad/market/settlement/v1`;
- local validation for market objects;
- signed object manifests;
- artifact bundle export and import;
- a simple static index of open bounties;
- manual settlement recorded back into PopperPad.

Then test with three bounty classes:

- break a parser or validator;
- reproduce a benchmark or theorem check;
- maintain a recipe after a dependency update.

## Promotion Boundary

Claims PopperPad can make after the MVP:

- PopperPad can record falsification-market objects append-only.
- Users can verify object integrity locally.
- Users can reproduce or challenge evidence without trusting a central index.
- Settlements can be linked to evidence bundles.

Claims PopperPad cannot make yet:

- The market is sybil-resistant.
- The token economics are attack-resistant.
- The system can settle arbitrary scientific disputes.
- Governance cannot be captured.
- Storage availability is guaranteed forever.

Those require separate evidence, adversarial modeling, and live-market data.

## Summary

The falsification market is a decentralized incentive layer around PopperPad's
scientific memory. It is more precisely a market for verifiable epistemic
artifacts. It pays for the work science needs most but often underfunds: proofs,
counterexamples, reproduction, preservation, formalization, verifier
improvement, and maintenance.

The design should stay disciplined:

- store scientific memory off-chain in content-addressed pads;
- settle bounties and bonds on-chain;
- reward proof, falsification, reproduction, and preservation;
- govern protocol parameters;
- never let token weight decide truth.
