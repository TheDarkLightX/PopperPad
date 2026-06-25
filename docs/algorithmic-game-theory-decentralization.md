# Algorithmic Game Theory Decentralization

Status: design draft.

PopperPad should decentralize as a proof-carrying epistemic artifact market, not as a truth-voting DAO. The market can route attention, escrow rewards, bond service providers, and settle payouts. It cannot decide scientific truth by payment or vote, but it can buy proof, refutation, reproduction, and replayable evidence.

Verifiers decide scoped check results. Lean can accept a theorem proof. A replay
harness can reproduce an experiment. A fuzzer can exhibit a counterexample.
PopperPad stores those truth-bearing results and derives graph status from the
objects, evidence, contexts, recipes, signatures, and the reader's trust policy.

## Design Goal

In Max Tegmark's terminology, "perceptronium" is matter with distinctive information-processing abilities. In PopperPad terms, every human, AI agent, lab, company, bot, verifier, storage node, and theorem prover can become an epistemic worker.

The incentive target is:

```text
Any agent with spare cognition, compute, storage, or expertise should earn more
by making claims testable, refuting bad claims, reproducing evidence, preserving
artifacts, and improving recipes than by posting noise.
```

The equilibrium target is:

```text
ExpectedPayoff(honest useful work)
  > ExpectedPayoff(spam, fake evidence, cartel attestation, unverifiable claims)
```

For an agent `i`:

```text
U_i = P_i + R_i - C_i - B_i
```

Where `P_i` is direct payout, `R_i` is typed reputation value, `C_i` is the cost of work, and `B_i` is expected bond loss or future eligibility loss from bad behavior.

## Strategic Knowledge Game

Define a PopperPad game:

```text
G = (N, A, S, V, P, C)
```

Where:

- `N` is the set of agents: claim authors, refuters, reproducers, recipe maintainers, storage nodes, indexers, curators, sponsors, governance participants, and autonomous AI workers.
- `A_i` is each agent's action space: publish claim, attach recipe, run check, submit counterexample, reproduce result, maintain old recipe, preserve artifact, index bundle, challenge fraud, sponsor bounty, or forecast claim survival.
- `S` is the PopperPad state: content-addressed objects, evidence bundles, append-only logs, signatures, market commitments, and typed graph edges.
- `V` is verified epistemic value: replayable updates to the claim graph.
- `P_i` is payout.
- `C_i` is the agent's cost.

The market should pay for verified epistemic delta, not raw content.

When a verifier can decide a scoped claim, PopperPad should pay for that
verifier-accepted result. In formal domains, this means paying for a proof or
counterexample accepted by the relevant checker. In empirical domains, it means
paying for reproducible evidence under a declared protocol.

Payment direction matters:

```text
Bad:  Payment -> ClaimAccepted
Good: VerifierAcceptedCertificate -> Payment
```

## Knowledge Patch

The atomic rewarded output is a knowledge patch:

```text
K = (h, c, r, e, a, sigma, pi)
```

Where:

- `h` is a hypothesis ref.
- `c` is a context ref.
- `r` is a recipe or check ref.
- `e` is an evidence ref.
- `a` is one or more artifact refs.
- `sigma` is signatures or attestations.
- `pi` is a proof, replay, counterexample, or certificate bundle.

A raw claim should receive little or no reward. A claim with a deterministic recipe is more useful. A claim with replayable evidence, independent reproduction, and survived challenges is more useful still. A counterexample that precisely breaks an important claim can be the highest-value output.

First-pass patch value:

```text
V(K) =
    alpha * Importance(h)
  + beta  * InformationGain(K)
  + gamma * ReproductionStrength(K)
  + delta * BoundaryValue(K)
  + eta   * MaintenanceValue(K)
  + theta * PreservationValue(K)
  - lambda * DuplicatePenalty(K)
  - mu     * FragilityPenalty(K)
  - nu     * SybilRisk(K)
```

Definitions:

- `Importance(h)` is sponsor demand, public-good value, or downstream dependency count.
- `InformationGain(K)` measures uncertainty removed by the patch.
- `ReproductionStrength(K)` measures independent, context-aware replay.
- `BoundaryValue(K)` rewards narrowing an overbroad claim into a sharper valid claim.
- `MaintenanceValue(K)` rewards keeping recipes and toolchains alive.
- `PreservationValue(K)` rewards durable artifact availability.
- `DuplicatePenalty(K)` discounts repeated work.
- `FragilityPenalty(K)` discounts flaky, nondeterministic, or underspecified evidence.
- `SybilRisk(K)` discounts suspiciously related actors.

## Anti-Fraud Constraint

Any role that can extract value by lying should satisfy:

```text
DefectGain <= DetectionProbability * SlashAmount + FutureValueLost
```

For fake evidence:

```text
G <= p * D + F
```

For fake attestation:

```text
R <= p * A + F
```

For fake storage claims:

```text
StorageReward <= p * S + F
```

Where:

- `G` is fraudulent gain.
- `R` is attestation reward.
- `D` is submitter bond.
- `A` is attester bond.
- `S` is storage bond.
- `p` is detection probability during audit or challenge.
- `F` is future value lost through reputation, deny lists, or reduced eligibility.

Slash only protocol-level misconduct: fake attestations, unavailable artifacts after claimed storage, malformed commitments, duplicate work presented as novel, invalid signatures, or scope mutation after bounty opening. Do not slash an honest claim author merely because a claim is refuted.

## Four Decentralization Planes

PopperPad decentralization should keep five functions separate:

```text
TruthComputation != Storage != Anchoring != Settlement != Governance
```

The existing adapter architecture maps cleanly to this rule.

### Object Plane

The object plane contains canonical PopperPad JSON objects: hypotheses, recipes, contexts, evidence, artifacts, bounties, submissions, attestations, challenges, settlements, and typed graph edges. Objects are content-addressed and locally verifiable.

### Storage Plane

The storage plane serves bytes through local filesystems, Git, HTTP, S3-compatible stores, IPFS, Filecoin, Arweave, chain-specific blob stores, or other content-addressed networks. Storage rewards should be tied to retrieval challenges and slashable availability commitments.

### Anchor Plane

The anchor plane records bundle roots, manifest roots, previous anchor links, timestamps, publisher identities, storage CIDs or content ids, and bounty or settlement commitments. Anchors make history harder to rewrite. They do not validate scientific claims.

### Market Plane

The market plane manages bounty escrow, submitter bonds, attester bonds, storage bonds, challenge deposits, reward settlement, slashing, and governance-controlled parameters. Market events become PopperPad metadata. They do not make a hypothesis true.

### Verification Plane

The verification plane remains local: schema checks, hash checks, signature checks, recipe execution, Lean, SMT, fuzzing, benchmark, or verifier portals, and trust policy evaluation.

The boundary is:

```text
ChainAccepts(root) does not imply ClaimTrue(h)

VerifierAccepts(certificate, context) -> checked result
PopperPad stores checked result -> graph status
```

## Mechanism Portfolio

No single market mechanism fits all scientific work. PopperPad should use a portfolio of mechanisms with explicit payout rules.

### Counterexample Bounties

Counterexample bounties pay for evidence that breaks a claim under a stated context.

```text
Bounty = (h, c, R, deadline, challengeWindow, payoutRule, escrow)
```

A submission becomes payable when:

- it was submitted before the deadline;
- it references the exact bounty and claim;
- required artifacts are available;
- required recipes run or the submission includes an accepted formal witness;
- the evidence contradicts the claim under the bounty context;
- the challenge window closes without a successful challenge.

Payout should reward:

```text
Novelty * Minimality * Severity * Reproducibility
```

A smaller minimized counterexample can earn a secondary reward because it makes the failure easier to remember and replay.

### Reproduction Bounties

Reproduction bounties pay independent agents to rerun checks:

```text
Run(recipe, context) -> PASS | FAIL | SKIP
```

Payout should distinguish:

- `PASS`: paid for independent confirmation.
- `FAIL`: paid more if novel, actionable, and well packaged.
- `SKIP`: paid little unless it exposes a real portability or dependency flaw.

### Boundary Bounties

Boundary bounties reward an agent who turns an overbroad claim into a sharper valid claim:

```text
h_old --counterexample--> h_new

h_new = h_old + explicit assumptions
```

The output should include original claim ref, counterexample ref, new scoped hypothesis ref, a supersedes, narrows, or refutes edge, and recipe evidence for the new claim where possible.

### Recipe Maintenance Bounties

Recipe maintenance bounties pay maintainers to keep old checks alive across toolchain, dependency, compiler, dataset, and hardware changes.

Payment should require:

```text
SemanticsPreserved(oldRecipe, newRecipe)
```

Evidence can include regression suites, golden outputs, SMT equivalence checks, Lean obligations, trusted replay, or bounded differential tests.

### Artifact Availability Bounties

Storage nodes post a bond, commit to serve a content hash, and earn through randomized retrieval challenges:

```text
StorageNode commits to blobRef = sha256(bytes)
```

Rewards require a content hash, storage duration, replication target, retrieval challenge success, and slashable availability bond.

### Curation and Indexing Bounties

Curators and indexers should be paid for useful graph maintenance, not for declaring truth. Useful edge work includes `duplicate_of`, `narrows`, `refutes`, `supports`, `transfers_to`, `supersedes`, and `equivalent_to`.

A delayed reward can pay curators when later verified work uses their clusters, indexes, or graph edges.

## Forecasting and Belief Markets

Prediction markets are useful for allocating attention. They must not decide claim status.

Useful forecast questions include the probability that a claim survives a challenge window, is refuted by a specific class of counterexample, reproduces on a specific platform, or receives a minimized counterexample before a deadline.

Strictly proper scoring rules or market scoring rules can reward honest probabilistic beliefs under the mechanism's assumptions:

```text
LogScore(p, y) = y * log(p) + (1 - y) * log(1 - p)

BrierScore(p, y) = -1 * (p - y)^2
```

But the boundary remains:

```text
PredictionMarketPrice(h) does not imply ClaimTrue(h)
```

Forecasts should feed task prioritization, bounty sizing, and review queues. They should not override local verification.

## Public-Good Funding

Private sponsors can fund claims they care about directly. Public-good claims need a different funding mechanism.

Quadratic funding can boost claim clusters supported by many independent small contributors:

```text
QFScore(project) = (sum_i sqrt(contribution_i))^2

MatchWeight = QFScore * IndependenceScore * SybilDiscount
```

Use quadratic funding for public benchmark replication, open-source verifier maintenance, medical or safety replication where data policy allows, cryptographic assumption testing, AI-safety benchmark validity, and formal proof library maintenance.

Quadratic funding requires anti-collusion controls. Matching funds can be exhausted quickly, and reciprocal backing can become strategic behavior.

## Peer Prediction for Slow or Subjective Work

Some PopperPad work is objectively replayable. Some work is slow, subjective, or only indirectly verifiable.

Use peer prediction only as a weak prioritization signal for explanation quality, claim scoping quality, cross-domain mapping usefulness, and expert review queue triage.

```text
SubjectiveScore -> CurationPriority
SubjectiveScore does not imply ClaimTrue(h)
```

## Universal Agent Work Loop

Autonomous workers should be able to operate against a machine-readable work market:

```text
scan open bounties
estimate expected value
choose target
fetch bundle
verify hashes
run recipe
search for counterexample or reproduction
shrink result
submit evidence bundle
post bond
survive challenge window
receive payout and typed reputation
```

Agent expected value:

```text
EV(task) = Pr(success) * Reward - Cost - Pr(slash) * Bond
```

An autonomous worker will choose PopperPad tasks when:

```text
EV(PopperPadTask) > EV(AlternativeComputeUse)
```

### Work Order Object

```json
{
  "schema": "popperpad/market/work-order/v1",
  "task_type": "counterexample",
  "claim_ref": "sha256:...",
  "context_ref": "sha256:...",
  "accepted_recipe_refs": ["sha256:..."],
  "max_payout": "1000 PPAD",
  "min_bond": "25 PPAD",
  "deadline": "2026-12-31T23:59:59Z",
  "challenge_window_seconds": 604800,
  "scoring": {
    "novelty_weight": 0.30,
    "minimality_weight": 0.20,
    "severity_weight": 0.30,
    "reproducibility_weight": 0.20
  }
}
```

## Typed Reputation

Avoid a single global trust score. Use typed, evidence-derived reputation:

```text
Rep(agent, domain, role)
```

Examples:

```text
Rep(did:example:alice, Lean, Reproducer)
Rep(did:example:bot42, RustFuzzing, Refuter)
Rep(did:example:storage7, ArtifactAvailability, Storage)
```

Useful reputation inputs include reproduced submissions, successful challenges, failed challenges, artifact availability history, recipe maintenance history, domains of competence, and signatures from locally trusted parties.

The trust policy remains local. A storage node's availability history should not make it a theorem authority. A theorem attester's history should not make it a genomics-data authority.

## Governance Boundary

Governance can control fee rates, bond minimums, challenge window durations, accepted schema versions, treasury grants, reward epoch budgets, storage-market parameters, and indexer service requirements.

Governance cannot control whether a claim is true, whether a user must trust an attester, whether local evidence can exist, or whether valid historical objects can be erased.

Tau-style governance can specify market rules, adapter requirements, bounty semantics, and upgrade constraints. It should decide market validity, not scientific reality.

```text
RulesDecide(MarketValidity)
Rules do not decide Reality
```

## Full Incentive Stack

| Layer | Mechanism | Incentivizes |
| --- | --- | --- |
| Claim | Small rewards for precise hypotheses | Better claim formation |
| Recipe | Maintenance bounties | Durable testability |
| Evidence | Counterexample and reproduction bounties | Falsification and confirmation |
| Forecast | Proper scoring or prediction markets | Honest belief aggregation |
| Funding | Quadratic funding with sybil discounts | Public-good priorities |
| Storage | Retrieval challenges and storage bonds | Evidence preservation |
| Curation | Delayed graph-utility rewards | Better semantic graph |
| Attestation | Bonded independent reproduction | Anti-rubber-stamp validation |
| Challenge | Challenger rewards and slashing | Fraud resistance |
| Governance | Parameter voting or Tau rules | Market evolution |

## Implementation Claims to Prove

The global mechanism cannot be proven correct all at once. PopperPad should prove smaller claims:

- fake evidence is unpayable when deterministic checks fail;
- unavailable artifacts are slashable through retrieval challenges;
- sponsor rug pulls are prevented by escrow;
- author claim mutation is prevented by content addressing;
- fake attestations have negative expected value under audit probability and bond sizing;
- token voting cannot alter local scientific status;
- raw popularity cannot promote a claim to supported.

## Executable Workbench

This design has two small executable artifacts:

- `models/mechanism_design/anti_fraud_bounds.jl` checks sample bounty, bond,
  audit, and reward profiles against the anti-fraud and honest-participation
  inequalities.
- `formal/PopperPadMechanism.lean` formalizes the core arithmetic theorem: when
  expected deterrence is at least the gain from cheating, the defecting utility
  is nonpositive.
- `popperpad/market/work-order/v1` is the first machine-readable market object
  for publishing epistemic tasks to humans, agents, provers, and storage nodes.
- `popperpad/market/resource-budget/v1` records accepted fuel assets, compute
  limits, storage limits, model/API limits, access paths, and the explicit
  boundary that resource funding does not buy truth.
- `popperpad/certificate/truth/v1` records the sellable truth-bearing artifact:
  claim, context, verifier, recipe, evidence, artifacts, signatures, and
  accepted verifier result.
- `popperpad/gamification/score-event/v1` records evidence-backed points,
  badges, streaks, reputation, season score, and optional token rewards without
  making game score decide claim truth.
- `popperpad/gamification/quest/v1` defines verifier-gated quests with accepted
  score-event kinds, point rewards, optional token budget refs, completion
  criteria, and anti-abuse limits.

These are deliberately narrow. They do not prove the whole market safe. They
turn the most important mechanism-design guardrails into replayable checks that
can be expanded as the market objects become executable.

## MVP Sequence

### Phase 0: Local Signed Market Objects

Implement bounty, submission, attestation, challenge, and settlement schemas; local `doctor` checks for market objects; signed manifests; duplicate detection by content hash and claim scope; and manual settlement recorded back into PopperPad.

### Phase 1: Bundle Publication

Implement canonical bundle manifests, local bundle export and import, IPFS or CAR publication, retrieval checks, local trust policies, chain anchor receipt format, and verification reports.

### Phase 2: Escrow With External Fuel Assets

Use Agoras, stablecoins, USD rails, grants, or manual payouts. Implement a bounty registry, escrow, bond manager, challenge manager, settlement contract, and resource-budget accounting for compute, storage, model calls, verifier runs, and retrieval.

### Phase 3: Bonded Attestation Network

Implement attester registration, bonded attestations, random or market-selected reproduction assignments, challengeable reproduction evidence, and typed reputation.

### Phase 4: Native Token If Demand Justifies It

Introduce a native PopperPad token only after the external-asset plus internal-credit market has evidence of real demand.

Token utility includes bounty funding, bonds, storage rewards, challenge deposits, indexer fees, and governance over protocol parameters.

Token non-utility includes deciding truth, overriding evidence, forcing trust, or mutating historical records.

### Phase 5: Federation, Tau Net, or Appchain

Consider a dedicated network only if volume, fees, storage proofs, or governance requirements justify it.

## Bottom Line

PopperPad gives broad cognition and compute an incentive to grow knowledge by turning each useful epistemic act into a paid, content-addressed, challengeable, locally verifiable work product.

The operating rule is:

```text
Pay agents to make being wrong cheaper to discover, being right easier to
reproduce, and old evidence harder to lose.
```

## References

- Max Tegmark, "Consciousness as a State of Matter," arXiv:1401.1219.
- Lance Fortnow and Rahul Sami, "Multi-outcome and Multidimensional Market Scoring Rules," arXiv:1202.1712.
- Vitalik Buterin, Zoe Hitzig, and E. Glen Weyl, "A Flexible Design for Funding Public Goods," arXiv:1809.06421.
- Ricardo A. Pasquini, "Quadratic Funding and Matching Funds Requirements," arXiv:2010.01193.
- Yuqing Kong and Grant Schoenebeck, "An Information Theoretic Framework For Designing Information Elicitation Mechanisms That Reward Truth-telling," arXiv:1605.01021.
