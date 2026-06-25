# Token Fuel Economics

Status: design draft.

PopperPad needs token-fueled economics from the beginning because decentralized
knowledge growth has real costs: storage, compute, model calls, verifier runs,
indexing, recipe maintenance, artifact preservation, and agent labor.

The corrected boundary is:

```text
Token as resource fuel: yes
Token as truth oracle: no
Token as rich-only participation gate: no
```

Tokens buy resources and reward epistemic labor. They do not buy reality.

## Immediate Asset Strategy

PopperPad should support external settlement assets immediately, including
Agoras, stablecoins, USD rails, grants, and manual settlement where appropriate.

The staged design is:

```text
AGRS or other accepted assets -> early settlement and resource fuel
PPAD credits                  -> internal compute and storage accounting
Native PPAD                   -> later network token if demand justifies it
```

Agoras is a natural first integration candidate because Tau describes `$AGRS` as
the token at the center of Tau Net's ecosystem and says the current ERC-20 token
is a placeholder to be swapped for a mainnet Agoras coin after Tau Net mainnet is
developed. PopperPad should still remain asset-agnostic enough to accept other
funding sources.

## Resource Meter

Agentic scientific memory is not free. A resource budget should meter:

```text
AgentRunCost =
    model_input_tokens
  + model_output_tokens
  + tool_calls
  + container_time
  + verifier_time
  + storage_written
  + retrieval_bandwidth
```

The exact prices are adapter-specific and time-varying. OpenAI's public API
pricing page, for example, lists per-token model costs and separate web-search
tool costs. PopperPad should therefore store price schedules as dated policy
objects, not hard-code model prices into the scientific record.

## Resource Budget Object

Resource budgets are separate from truth claims. They fund work orders.

```json
{
  "schema": "popperpad/market/resource-budget/v1",
  "budget_id": "counterexample-search-budget-001",
  "work_order_ref": "sha256:...",
  "payer_ref": "did:example:sponsor",
  "settlement_assets": ["AGRS", "USDC", "PPAD_CREDIT"],
  "limits": {
    "compute": "15 AGRS",
    "storage": "2 AGRS",
    "api": "30 USD",
    "verifier": "10 AGRS",
    "retrieval": "3 AGRS"
  },
  "access_paths": ["pay", "earn", "grant", "local"],
  "model_policy": {
    "cheap_model_first": true,
    "max_paid_escalations": 2
  },
  "truth_boundary": "resource_funding_only"
}
```

The `truth_boundary` value is intentionally explicit. Spending more can fund
more attempts, storage, or verification. It cannot mark a claim supported.

The canonical schema is `schemas/v1/market_resource_budget.schema.json`, and the
runtime validator accepts the object as `popperpad/market/resource-budget/v1`.

## Access Paths

PopperPad should support four ways to participate:

- `pay`: a user, company, DAO, or lab funds a bounty or resource budget.
- `earn`: a contributor earns credits through reproduction, refutation,
  curation, recipe maintenance, storage, or compute donation.
- `grant`: the treasury funds public-good work.
- `local`: anyone can run local PopperPad without joining the network economy.

The fairness target is:

```text
UsefulWork -> Credits -> MoreCompute -> MoreUsefulWork
```

This avoids a rich-only network. A capable contributor should be able to earn
compute and storage access before spending money.

## Treasury

The epistemic treasury funds valuable work without obvious private sponsors.

Inflows:

- protocol fees;
- sponsor bounties;
- donations;
- grants;
- slashed fraud bonds;
- storage fees;
- indexing fees;
- optional native-token emissions after governance approval.

Outflows:

- agent compute grants;
- storage subsidies;
- public-good bounties;
- reproduction rewards;
- counterexample rewards;
- recipe maintenance rewards;
- model/API credits;
- verifier infrastructure.

Treasury safety condition:

```text
AvailableTreasury + EpochInflows >= CommittedOutflows + ReserveRequirement
```

The executable check in `models/mechanism_design/resource_fuel_bounds.jl`
includes this treasury condition, resource-budget coverage, and earn-before-spend
access.

## Storage Economics

PopperPad should not promise unlimited storage. It should promise bounded,
prioritized, replicated, retrieval-checked storage.

Storage reward:

```text
StorageReward =
    BaseAvailabilityReward
  * ImportanceBonus
  * RetrievalSuccessBonus
  * ReplicationBonus
  - DuplicatePenalty
  - UnavailableSlash
```

Storage tiers:

| Tier | Who pays | What gets stored |
| --- | --- | --- |
| Local private pad | User | Anything they want locally |
| Public claim metadata | Network subsidy | Small canonical objects |
| High-value evidence bundles | Sponsor or treasury | Important artifacts, traces, proofs |
| Massive datasets | Special storage market | Data whose value justifies cost |
| Popular mirrors | Storage demand | Frequently retrieved bundles |
| Archival public goods | Treasury or quadratic funding | Historically important evidence |

## Compute Market

PopperPad should route tasks through a compute market:

```text
Task + Budget + Reward -> AgentExecution
```

Agent bid:

```text
Bid_i = ExpectedCost_i + Margin_i
```

Selection score:

```text
Score_i =
    Reliability_i
  * DomainReputation_i
  * CostEfficiency_i
  * DiversityBonus_i
  - SybilRisk_i
```

The default model-routing policy should be:

```text
cheap model -> stronger model -> deterministic verifier
```

Expensive models and paid tool calls should be used when the expected value of
the task justifies escalation.

## Native Token Trigger

A native PopperPad token is justified when the network has enough activity that
external assets and non-transferable credits are no longer enough.

Possible triggers:

- sustained bounty volume;
- recurring storage-market demand;
- active agent-run marketplace;
- treasury-managed public-good budgets;
- repeated need for PopperPad-specific emissions;
- governance demand for PopperPad-specific resource policy.

Before that point, PopperPad can use Agoras, stablecoins, USD rails, donations,
and internal credits.

## Hard Non-Goals

The token must not:

- decide truth;
- override evidence;
- force users to trust a claim;
- censor local pads;
- mutate historical records;
- make scientific status a function of stake.

Correct boundary:

```text
Stake -> funds work
Verifier accepts proof/counterexample/replay -> checked result
PopperPad stores checked result -> local graph status
```

Sharper doctrine:

```text
Token payment -> proof work -> verifier pass -> supported status
Token stake alone -> no status change
```

Truth is for sale only as proof-carrying truth: a verifiable, replayable,
scope-bound certificate under explicit assumptions.

The Lean file `formal/PopperPadTruthBoundary.lean` captures this boundary by
proving that changing token stake alone does not change local status when the
verifier result and local status inputs are unchanged.

## References

- Tau Net, "Agoras," https://tau.net/agoras/.
- OpenAI, "API Pricing," https://openai.com/api/pricing/.
