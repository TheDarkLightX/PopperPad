# Tokenomics Decision: External Assets First

## Status

Accepted - Issue #6

## Context

PopperPad needs a way to incentivize falsification work, verification, and reproduction. The question is whether to launch with a native token (PPAD) or use external assets first.

## Decision

We will validate the bounty model using external assets (manual settlement, grants, USD, stablecoins, non-transferable credits) before considering any native token or appchain.

## Rationale

1. **Demand validation first**: A token cannot create product-market fit. We must prove that users will pay for verified falsification work using existing payment methods.

2. **Preserve core principle**: Money funds scarce work; verifier evidence changes claim status. This works independently of the payment mechanism.

3. **Reduce risk**: Launching a token introduces legal, regulatory, market manipulation, and governance risks that are unnecessary until the core value proposition is proven.

4. **Iterate faster**: Off-chain settlement allows rapid iteration on bounty mechanics, payout rules, and verification workflows without smart contract upgrades.

## Consequences

### Positive

- Focus on core product value rather than token mechanics
- Faster iteration on bounty and settlement workflows
- Lower regulatory and legal risk during alpha
- Clearer signal about actual demand

### Negative

- Manual settlement overhead for early bounties
- No automated escrow or trustless payout enforcement
- Limited to users who can access external payment methods

### Neutral

- Settlement records remain append-only in PopperPad regardless of payment mechanism
- Architecture must support eventual smart contract integration

## Implementation Path

See [Bounty Pilot Plan](../bounty-pilot-plan.md) for detailed requirements and metrics.
