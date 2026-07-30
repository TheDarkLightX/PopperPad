# PopperPad Roadmap

## Current Phase: Public Alpha

### Pre-token Bounty Pilot

Validate the falsification bounty model using external assets before considering native tokens or an appchain. See [Bounty Pilot Plan](docs/bounty-pilot-plan.md) for details.

**Key Objectives:**
- Prove sponsors will repeatedly pay for verified falsification work
- Validate bounty mechanics, verification workflows, and settlement processes
- Measure real costs and conversion rates across 20+ completed bounties
- Build required market objects (bounties, submissions, verifier receipts, challenges, settlements)

**Bounty Classes:**
1. Software counterexamples (minimized failing inputs + regression tests)
2. Formal counterexamples/reproductions (Lean/SMT witnesses, independent replays)
3. Recipe maintenance (restore deterministic replay after dependency changes)

**Settlement Methods:**
- Manual settlement
- Grants and sponsorships
- USD rails
- Stablecoins
- Non-transferable PopperPad credits

### Smart Contract Consideration

Smart contract escrow will be considered only when the pilot demonstrates a real trust/coordination failure that contracts solve:
- Sponsor rug risk
- Deadline enforcement
- Bonded availability
- Cross-party payout enforcement

If needed, start with chain-neutral escrow/commitment adapters rather than an appchain.

### Native Token Consideration

A native PPAD token will be considered only when ALL of the following are evidenced:
- Sustained external demand for bounties and resource credits
- A recurring multi-sided economy (sponsors, searchers, verifiers, reproducers, storage providers, indexers)
- Existing assets/credits create a measurable coordination or monetary-policy problem
- P0 sandbox, verifier-receipt, import, custody, and audit gates are complete
- Token utility is independent of deciding truth
- Legal, tax, market-manipulation, governance-capture, and liquidity risks have been reviewed

### Kill Criterion

If sponsors will not repeatedly pay for verified counterexamples/reproductions under manual or external-asset settlement, a native token will not fix product demand and must not be used to manufacture it.

## Future Phases

Future phases will be defined based on pilot results and validated demand.
