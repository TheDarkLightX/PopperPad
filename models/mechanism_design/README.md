# PopperPad Mechanism Design Workbench

This directory contains executable checks for the decentralized falsification
market design.

The first model is intentionally small. It checks two required inequalities:

```text
DefectGain <= DetectionProbability * SlashAmount + FutureValueLost
ExpectedHonestPayoff > 0
```

The first condition makes fake evidence, fake attestation, and fake storage
claims unprofitable under the modeled audit probability, bond size, and future
eligibility loss. The second condition makes useful work attractive enough for
humans, agents, provers, and storage nodes to participate.

Run:

```bash
julia models/mechanism_design/anti_fraud_bounds.jl
julia models/mechanism_design/resource_fuel_bounds.jl
julia models/mechanism_design/gamification_rewards.jl
julia models/mechanism_design/certificate_market.jl
```

Each script exits nonzero if any modeled class violates its inequality.

`resource_fuel_bounds.jl` checks three extra conditions:

```text
FundedBudget >= ResourceCost
AvailableTreasury + Inflows >= CommittedOutflows + ReserveRequirement
EarnedCredits >= MinimumAgentRunCost
```

These conditions encode the revised token-fuel stance: the network should pay
for real storage, compute, API, verifier, and retrieval costs, while still giving
contributors an earn path before they spend money.

`gamification_rewards.jl` checks that accepted proof, refutation, reproduction,
and storage work can earn points and token rewards, while unsupported popularity
earns zero.

`certificate_market.jl` checks the sharper doctrine:

```text
VerifierAcceptedCertificate -> Payment
Payment alone -> no truth status and no certificate payout
```
