# Bounty Pilot Plan

This document outlines the pre-token pilot for validating the PopperPad falsification bounty model using external assets before considering native tokens or an appchain.

## Decision

Do **not** launch a native PopperPad token or dedicated chain for the current public alpha. First prove that users will fund, perform, verify, reproduce, and settle epistemic work through the existing off-chain object model.

This preserves the intended principle: money funds scarce work; verifier evidence changes claim status.

## Pre-token Pilot Approach

Use manual settlement, grants, USD rails, stablecoins, Agoras, or non-transferable PopperPad credits. Keep settlement append-only in PopperPad even when payment occurs externally.

Run a bounded pilot across three objective bounty classes:

1. **Software counterexample:** produce a minimized failing input plus regression test.
2. **Formal counterexample/reproduction:** produce a Lean/SMT/verifier-accepted witness or independently replay an existing result.
3. **Recipe maintenance:** restore deterministic replay after a dependency/toolchain change.

## Required Pre-chain Market Objects

- [ ] bounty/work order with exact claim, context, accepted recipes/verifiers, budget, deadline, and payout rule
- [ ] submission with canonical witness/artifact refs
- [ ] verifier receipt and reproduction attestation
- [ ] challenge with objective reason/evidence
- [ ] deterministic settlement plan and append-only settlement receipt
- [ ] duplicate/novelty detection
- [ ] contributor earn path so participation is not limited to users who can prepay credits

## Pilot Metrics

For at least 20 completed bounties, measure:

- sponsor conversion and repeat funding
- time to first valid submission
- verification and independent-reproduction rates
- duplicate and invalid-submission rates
- compute/API/storage/verifier cost per accepted result
- dispute/challenge frequency and resolution time
- contributor earnings versus execution cost
- percentage of settlements that can be decided mechanically from predeclared rules

## Smart-contract Launch Gate

Add chain escrow only when the pilot demonstrates a real trust/coordination failure that contracts solve, such as sponsor rug risk, deadline enforcement, bonded availability, or cross-party payout enforcement. Start with chain-neutral escrow/commitment adapters; do not build an appchain.

## Native PPAD Launch Gate

Consider native PPAD only when all of the following are evidenced:

- sustained external demand for bounties and resource credits
- a recurring multi-sided economy of sponsors, searchers, verifiers, reproducers, storage providers, and indexers
- existing assets/credits create a measurable coordination or monetary-policy problem
- P0 sandbox, verifier-receipt, import, custody, and audit gates are complete
- token utility is independent of deciding truth
- legal, tax, market-manipulation, governance-capture, and liquidity risks have been reviewed

## Kill Criterion

If sponsors will not repeatedly pay for verified counterexamples/reproductions under manual or external-asset settlement, a native token will not fix product demand and must not be used to manufacture it.
