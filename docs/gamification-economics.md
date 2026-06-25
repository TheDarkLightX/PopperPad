# Gamification Economics

Status: design draft.

PopperPad should gamify knowledge growth. Points, badges, quests, streaks,
leaderboards, and token rewards can make the falsification market legible and
fun while still staying verifier-gated.

The rule is:

```text
Pay and score truth-bearing work, not truth claims by assertion.
```

In token terms:

```text
Truth certificates funded by payment: yes
Truth by payment, vote, or popularity: no
```

Tokens and points should reward accepted proofs, verified counterexamples,
reproductions, recipe maintenance, artifact preservation, useful curation, and
completed quests. They should not reward popularity, unsupported opinions, or
stake-weighted truth votes.

## Two Reward Channels

Use two distinct reward channels:

- `points`: non-transferable XP, reputation, badges, streaks, season score, and
  role-specific status.
- `tokens`: transferable or redeemable rewards for scarce resources and
  economically valuable work.

Points create motivation and discovery. Tokens pay for storage, compute, model
calls, verifier runs, maintenance, and labor.

The split matters:

```text
Points -> motivation, progression, matchmaking, visibility
Tokens -> resource funding, bounties, bonds, rewards
Verifier result -> checked truth-bearing work
PopperPad -> scientific memory and game state
```

## Core Loops

### Proof Quest

1. A theorem, invariant, or claim is posted with an accepted verifier.
2. The work order offers XP, reputation, and token reward.
3. A contributor submits a proof or counterexample.
4. The verifier accepts or rejects the certificate.
5. PopperPad records evidence, score events, and payout metadata.

### Reproduction Quest

1. A claim has a recipe and context.
2. Contributors rerun the recipe on declared platforms.
3. Reproducible `PASS`, novel `FAIL`, and useful `SKIP` results receive
   different point and token weights.
4. Streaks reward sustained independent reproduction, not duplicate spam.

### Boundary Quest

1. A broad claim fails.
2. A contributor finds the exact failure boundary.
3. The contributor submits a narrowed claim, counterexample, and supersession
   edge.
4. Points and token rewards favor precision, minimality, and reproducibility.

### Preservation Quest

1. A high-value evidence bundle needs durable storage.
2. Storage nodes earn points and tokens through retrieval challenges.
3. Missed retrievals lose points and can trigger slashing if bonded.

## Score Event Object

Gamification should be append-only and evidence-backed.

```json
{
  "schema": "popperpad/gamification/score-event/v1",
  "event_id": "proof-accepted-001",
  "agent_ref": "did:example:prover",
  "event_kind": "proof_accepted",
  "point_kind": "xp",
  "point_delta": 250,
  "subject_ref": "sha256:...",
  "domain_ref": "sha256:...",
  "evidence_refs": ["sha256:..."],
  "token_reward": "12 AGRS",
  "anti_abuse": {
    "verifier_required": true,
    "sybil_risk": 0.05
  },
  "truth_boundary": "gamification_only"
}
```

The canonical schema is `schemas/v1/gamification_score_event.schema.json`, and
the runtime validator accepts it as `popperpad/gamification/score-event/v1`.

## Quest Object

Quests define the work to be done. Score events record completed work.

```json
{
  "schema": "popperpad/gamification/quest/v1",
  "quest_id": "lean-proof-week-001",
  "title": "Prove or refute a queued Lean theorem",
  "quest_type": "proof",
  "domain_ref": "sha256:...",
  "objective": {
    "summary": "Submit a verifier-accepted proof or counterexample.",
    "target_ref": "sha256:..."
  },
  "accepted_event_kinds": ["proof_accepted", "counterexample_verified"],
  "rewards": {
    "points": {
      "xp": 500,
      "reputation": 25,
      "season_score": 100
    },
    "token_budget_ref": "sha256:..."
  },
  "completion": {
    "required_evidence_count": 1,
    "deadline": "2026-12-31T23:59:59Z"
  },
  "anti_abuse": {
    "max_rewards_per_agent": 3,
    "requires_independent_reproduction": true
  },
  "truth_boundary": "gamification_only"
}
```

The canonical schema is `schemas/v1/gamification_quest.schema.json`, and the
runtime validator accepts it as `popperpad/gamification/quest/v1`.

## Point Types

PopperPad should keep point types separate:

- `xp`: broad progression, mostly for usability and retention.
- `reputation`: role and domain-specific credibility.
- `season_score`: time-boxed competition score.
- `badge`: durable achievement for a specific class of work.
- `streak`: repeated useful work over time.

Avoid a single global score. A high score in Lean proof repair should not imply
authority in wet-lab reproduction or storage availability.

## Token Rewards

Tokens can deepen gamification because rewards become useful:

- pay for future agent runs;
- fund storage;
- post bonds;
- open bounties;
- buy verifier time;
- reward collaborators;
- compound useful work into more useful work.

The fairness loop is:

```text
Useful work -> points + credits/tokens -> more compute/storage access -> more useful work
```

This is the anti-rich-only path. Users should be able to earn their way into
more compute and storage by doing verifier-backed work.

## Leaderboards

Leaderboards should be scoped:

- by domain;
- by role;
- by season;
- by verifier;
- by quest type;
- by independent reproduction cohort.

Do not use one global leaderboard for all truth. Use many local boards that help
people find collaborators, rivals, mentors, and open quests.

## Anti-Abuse Rules

Gamification creates attack surfaces. Guardrails:

- Score only evidence-backed events.
- Weight verifier-accepted results above social signals.
- Penalize duplicates and low-effort repeated submissions.
- Discount suspicious sybil clusters.
- Cap repeated rewards for the same claim, agent cluster, or artifact.
- Separate novelty points from reproduction points.
- Make token rewards challengeable before settlement.
- Keep local PopperPad use independent of the game economy.

## Reward Formula

First-pass score:

```text
ScoreDelta =
    BaseQuestPoints
  * VerifierWeight
  * NoveltyWeight
  * ReproducibilityWeight
  * DifficultyWeight
  * DomainNeedWeight
  - DuplicatePenalty
  - SybilPenalty
  - FlakinessPenalty
```

Token reward can use the same inputs, but should also account for actual costs:

```text
TokenReward =
    WorkValue
  + CostReimbursement
  + PublicGoodSubsidy
  - ChallengeRiskDiscount
```

Points are allowed to be playful. Token rewards must be economically sane.

The executable check in `models/mechanism_design/gamification_rewards.jl`
exercises this rule with accepted proof/refutation/storage cases and an
unsupported popularity case that must receive zero.

## Deterministic Leaderboards

Leaderboards should be derived views over append-only score events, not mutable
state. PopperPad provides a projection helper and CLI command:

```bash
popperpad --pad ./pad gamification-leaderboard --point-kind xp --limit 20
```

The projection validates score events before counting them. Public indexes may
run in non-strict mode to skip malformed events while `popperpad doctor` or
schema validation reports the underlying issue.

## Truth Boundary

Gamification must not turn into truth voting.

Correct:

```text
Verifier accepts certificate -> score event and possible token reward
Points -> progression and visibility
Tokens -> resources and rewards
PopperPad -> stores the checked result and score event
```

Incorrect:

```text
Points or tokens -> claim is true
```

## MVP

Start with:

- score-event schema and validator;
- XP for verifier-accepted proof, counterexample, and reproduction events;
- role-specific reputation for refuters, reproducers, maintainers, curators, and
  storage nodes;
- seasonal leaderboards by domain and role;
- token rewards only for evidence-backed work orders;
- duplicate and sybil-risk discounts in settlement policy.

The game should make useful truth work visible, rewarding, and repeatable.
