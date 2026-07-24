# ESSO assurance for the falsification market

PopperPad's market transition is a strict FCIS state machine. The authoritative
runtime function consumes an immutable `BountyState`, one closed
`MarketCommand`, and immutable `MarketPolicy`, and returns exactly one of
`Accept`, `Reject`, or `CommittedFailure`. Files, clocks, verifiers, payments,
and chain clients remain shell concerns.

The corresponding ESSO profile is identified by
`popperpad.falsification-market.single-slot.v1`. Its binding contract is stored
at `formal/esso/popperpad_market_profile_v1.json`; the executable ESSO model and
checker live in `TheDarkLightX/ESSO` under `examples/popperpad/`.

## Assurance flow

```text
ESSO finite market specification
  -> canonical ESSO-IR validation
  -> Z3 Init => Inv and Inv & Guard => Inv(post)
  -> named disaster mutants require concrete counterexamples
  -> post-window challenge-resolution trace
  -> every reachable model state/action pair
  -> persistent strict JSON-lines runtime adapter
  -> exact decision/state/effect comparison
  -> source-pinned assurance report
```

The adapter is intentionally a value boundary. It accepts one canonical JSON
state and command, constructs the corresponding typed PopperPad state and
command, invokes the pure market transition, and projects the returned decision
back to the finite abstraction. It does not read a database, clock, network, or
chain.

## Defect found by formalization

The first model exposed a market deadlock: an open challenge could no longer be
resolved after the challenge window, while advancement refused to proceed while
the challenge remained open. The repaired rule is:

- the challenge window limits **opening** a challenge;
- a challenge opened in time remains resolvable afterward;
- advancement still waits for that challenge to resolve.

The ESSO checker retains the old behavior as a disaster mutant and requires a
concrete trace to kill it.

## Proved finite claims

For the declared one-bounty, one-submission, one-challenge abstraction, the
proof gate checks escrow, bond, and deposit conservation; terminal release of
locked value; exact settlement/refund; honest-verifier rejection without
slashing; slashing only after the corresponding challenge outcome; payable
eligibility; and post-window resolvability of an already-open challenge.

The mounted refinement gate checks every reachable abstract state against every
model action. An enabled model action must produce the same decision class,
post-state, and effect values in PopperPad. A disabled action must be rejected
without changing state or producing a receipt.

## Nonclaims

This evidence does not prove the human specification correct, arbitrary market
cardinality, unbounded liveness or fairness, verifier truth, production storage
linearizability, external destination idempotency, or any blockchain/token
implementation. Those are separate refinement and assurance obligations.
