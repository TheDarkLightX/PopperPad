from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

from .core.codec import canonical_hash, canonical_json_bytes
from .core.market import (
    AdvanceBounty,
    BountyPhase,
    BountyState,
    BountyTerms,
    CancelBounty,
    ChallengeState,
    ChallengeStatus,
    MarketCommand,
    MarketEffect,
    MarketPolicy,
    OpenBounty,
    OpenChallenge,
    Payout,
    ResolveChallenge,
    SettleBounty,
    SubmissionState,
    SubmissionStatus,
    SubmitCandidate,
    VerifySubmission,
    apply_market_command,
    bounty_state_violations,
)
from .core.result import Accept, CommittedFailure, Reject
from .core.values import Amount, FrozenDict, JsonValue, freeze_json, thaw_json


SCHEMA = "popperpad/esso-market-step/v1"
RESULT_SCHEMA = "popperpad/esso-market-result/v1"
ABSTRACTION_ID = "popperpad.falsification-market.single-slot.v1"

CLAIM_REF = "sha256:" + "a" * 64
CONTEXT_REF = "sha256:" + "b" * 64
RECIPE_REF = "sha256:" + "c" * 64
VERIFIER_REF = "sha256:" + "d" * 64
EVIDENCE_REF = "sha256:" + "e" * 64
ARTIFACT_REF = "sha256:" + "f" * 64
VERIFIER_RECEIPT_REF = "sha256:" + "1" * 64
CHALLENGE_EVIDENCE_REF = "sha256:" + "2" * 64
CHALLENGE_RECEIPT_REF = "sha256:" + "3" * 64

BOUNTY_ID = "bounty-1"
SUBMISSION_ID = "submission-1"
CHALLENGE_ID = "challenge-1"
SPONSOR_REF = "did:example:sponsor"
SUBMITTER_REF = "did:example:refuter"
CHALLENGER_REF = "did:example:challenger"
SETTLEMENT_REF = "chain:tx:1"

REWARD_ATOMS = 2
BOND_ATOMS = 1
DEPOSIT_ATOMS = 1
DEADLINE_EPOCH_S = 10
CHALLENGE_DEADLINE_EPOCH_S = 20

_PHASES = frozenset(value.name.title() for value in BountyPhase)
_SUBMISSIONS = frozenset({"None", *(value.name.title() for value in SubmissionStatus)})
_CHALLENGES = frozenset({"None", *(value.name.title() for value in ChallengeStatus)})
_COMMAND_KINDS = frozenset(
    {
        "open_bounty",
        "close_deadline",
        "submit_candidate",
        "verify_accept",
        "verify_reject",
        "open_challenge",
        "close_challenge_window",
        "resolve_upheld",
        "resolve_rejected",
        "advance",
        "settle",
        "cancel",
    }
)
_COUNTER_FIELDS = (
    "payout_atoms",
    "escrow_refund_atoms",
    "bond_refund_atoms",
    "bond_slashed_atoms",
    "deposit_refund_atoms",
    "deposit_slashed_atoms",
)
_STATE_FIELDS = frozenset(
    {
        "phase",
        "escrow_atoms",
        "submission",
        "bond_atoms",
        "challenge",
        "deposit_atoms",
        "deadline_closed",
        "challenge_window_closed",
        "resolution_enabled",
        *_COUNTER_FIELDS,
    }
)


@dataclass(frozen=True, slots=True)
class AbstractMarketState:
    phase: str
    escrow_atoms: int
    submission: str
    bond_atoms: int
    challenge: str
    deposit_atoms: int
    deadline_closed: bool
    challenge_window_closed: bool
    resolution_enabled: bool
    payout_atoms: int
    escrow_refund_atoms: int
    bond_refund_atoms: int
    bond_slashed_atoms: int
    deposit_refund_atoms: int
    deposit_slashed_atoms: int

    def __post_init__(self) -> None:
        violations = abstract_state_violations(self)
        if violations:
            raise ValueError(f"invalid abstract market state: {",".join(violations)}")

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "phase": self.phase,
                "escrow_atoms": self.escrow_atoms,
                "submission": self.submission,
                "bond_atoms": self.bond_atoms,
                "challenge": self.challenge,
                "deposit_atoms": self.deposit_atoms,
                "deadline_closed": self.deadline_closed,
                "challenge_window_closed": self.challenge_window_closed,
                "resolution_enabled": self.resolution_enabled,
                "payout_atoms": self.payout_atoms,
                "escrow_refund_atoms": self.escrow_refund_atoms,
                "bond_refund_atoms": self.bond_refund_atoms,
                "bond_slashed_atoms": self.bond_slashed_atoms,
                "deposit_refund_atoms": self.deposit_refund_atoms,
                "deposit_slashed_atoms": self.deposit_slashed_atoms,
            }
        )
        assert isinstance(value, FrozenDict)
        return value

    @staticmethod
    def from_mapping(value: Mapping[str, Any]) -> "AbstractMarketState":
        if set(value) != _STATE_FIELDS:
            missing = sorted(_STATE_FIELDS - set(value))
            extra = sorted(set(value) - _STATE_FIELDS)
            raise ValueError(f"state fields differ: missing={missing}, extra={extra}")
        for field in ("deadline_closed", "challenge_window_closed", "resolution_enabled"):
            if type(value[field]) is not bool:
                raise TypeError(f"{field} must be exact bool")
        for field in {"escrow_atoms", "bond_atoms", "deposit_atoms", *_COUNTER_FIELDS}:
            if type(value[field]) is not int:
                raise TypeError(f"{field} must be exact int")
        for field in ("phase", "submission", "challenge"):
            if type(value[field]) is not str:
                raise TypeError(f"{field} must be exact str")
        return AbstractMarketState(**{field: value[field] for field in AbstractMarketState.__dataclass_fields__})


def initial_abstract_state() -> AbstractMarketState:
    return AbstractMarketState(
        phase="Draft",
        escrow_atoms=0,
        submission="None",
        bond_atoms=0,
        challenge="None",
        deposit_atoms=0,
        deadline_closed=False,
        challenge_window_closed=False,
        resolution_enabled=False,
        payout_atoms=0,
        escrow_refund_atoms=0,
        bond_refund_atoms=0,
        bond_slashed_atoms=0,
        deposit_refund_atoms=0,
        deposit_slashed_atoms=0,
    )


def abstract_state_violations(state: AbstractMarketState) -> tuple[str, ...]:
    violations: list[str] = []
    if state.phase not in _PHASES:
        violations.append("phase")
    if state.submission not in _SUBMISSIONS:
        violations.append("submission")
    if state.challenge not in _CHALLENGES:
        violations.append("challenge")
    for field, maximum in (
        ("escrow_atoms", REWARD_ATOMS),
        ("bond_atoms", BOND_ATOMS),
        ("deposit_atoms", DEPOSIT_ATOMS),
        ("payout_atoms", REWARD_ATOMS),
        ("escrow_refund_atoms", REWARD_ATOMS),
        ("bond_refund_atoms", BOND_ATOMS),
        ("bond_slashed_atoms", BOND_ATOMS),
        ("deposit_refund_atoms", DEPOSIT_ATOMS),
        ("deposit_slashed_atoms", DEPOSIT_ATOMS),
    ):
        value = getattr(state, field)
        if type(value) is not int or not 0 <= value <= maximum:
            violations.append(field)
    if type(state.deadline_closed) is not bool or type(state.challenge_window_closed) is not bool:
        violations.append("time_flags")
    if state.challenge_window_closed and not state.deadline_closed:
        violations.append("window_before_deadline")

    total_escrow = state.escrow_atoms + state.payout_atoms + state.escrow_refund_atoms
    if state.phase == "Draft":
        if total_escrow != 0:
            violations.append("draft_escrow_conservation")
    elif total_escrow != REWARD_ATOMS:
        violations.append("escrow_conservation")

    total_bond = state.bond_atoms + state.bond_refund_atoms + state.bond_slashed_atoms
    expected_bond = 0 if state.submission == "None" else BOND_ATOMS
    if total_bond != expected_bond:
        violations.append("bond_conservation")

    total_deposit = state.deposit_atoms + state.deposit_refund_atoms + state.deposit_slashed_atoms
    expected_deposit = 0 if state.challenge == "None" else DEPOSIT_ATOMS
    if total_deposit != expected_deposit:
        violations.append("deposit_conservation")

    if state.phase in {"Open", "Payable"} and state.escrow_atoms != REWARD_ATOMS:
        violations.append("active_escrow")
    if state.phase in {"Settled", "Expired", "Canceled"}:
        if state.escrow_atoms or state.bond_atoms or state.deposit_atoms:
            violations.append("terminal_lock")
    if state.phase == "Payable":
        if state.submission != "Verified" or state.challenge == "Open":
            violations.append("payable_eligibility")
    if state.phase == "Settled" and state.payout_atoms != REWARD_ATOMS:
        violations.append("settlement_exact")
    if state.phase in {"Expired", "Canceled"} and state.escrow_refund_atoms != REWARD_ATOMS:
        violations.append("refund_exact")
    if state.phase == "Canceled" and (state.submission != "None" or state.challenge != "None"):
        violations.append("canceled_activity")
    if state.submission == "None" and (state.bond_atoms or state.bond_refund_atoms or state.bond_slashed_atoms):
        violations.append("bond_without_submission")
    if state.submission == "Rejected" and state.bond_atoms:
        violations.append("rejected_bond")
    if state.challenge == "None" and (state.deposit_atoms or state.deposit_refund_atoms or state.deposit_slashed_atoms):
        violations.append("deposit_without_challenge")
    if state.challenge == "Open":
        if not state.resolution_enabled:
            violations.append("open_challenge_not_resolvable")
        if state.phase != "Open" or state.submission != "Verified":
            violations.append("open_challenge_context")
        if state.deposit_atoms != DEPOSIT_ATOMS:
            violations.append("open_challenge_deposit")
    if state.challenge != "Open" and state.resolution_enabled:
        violations.append("resolution_enabled_without_open_challenge")
    if state.challenge in {"Upheld", "Rejected"} and state.deposit_atoms:
        violations.append("resolved_challenge_deposit")
    if state.bond_slashed_atoms and state.challenge != "Upheld":
        violations.append("unjustified_bond_slash")
    if state.deposit_slashed_atoms and state.challenge != "Rejected":
        violations.append("unjustified_deposit_slash")
    if state.challenge == "Upheld" and state.submission != "Rejected":
        violations.append("upheld_challenge_submission")
    if state.submission == "Rejected" and state.challenge == "None":
        if state.bond_refund_atoms != BOND_ATOMS or state.bond_slashed_atoms != 0:
            violations.append("honest_rejection_settlement")
    if state.challenge == "Upheld":
        if state.bond_slashed_atoms != BOND_ATOMS or state.deposit_refund_atoms != DEPOSIT_ATOMS:
            violations.append("upheld_challenge_settlement")
    if state.challenge == "Rejected" and state.deposit_slashed_atoms != DEPOSIT_ATOMS:
        violations.append("rejected_challenge_settlement")
    return tuple(sorted(set(violations)))


def _terms() -> BountyTerms:
    return BountyTerms(
        bounty_id=BOUNTY_ID,
        sponsor_ref=SPONSOR_REF,
        claim_ref=CLAIM_REF,
        context_ref=CONTEXT_REF,
        reward=Amount(REWARD_ATOMS),
        minimum_submission_bond=Amount(BOND_ATOMS),
        deadline_epoch_s=DEADLINE_EPOCH_S,
        challenge_window_seconds=CHALLENGE_DEADLINE_EPOCH_S - DEADLINE_EPOCH_S,
        accepted_recipe_refs=frozenset({RECIPE_REF}),
        accepted_verifier_refs=frozenset({VERIFIER_REF}),
    )


def _policy() -> MarketPolicy:
    return MarketPolicy(
        minimum_bounty=Amount(REWARD_ATOMS),
        minimum_submission_bond=Amount(BOND_ATOMS),
        minimum_challenge_deposit=Amount(DEPOSIT_ATOMS),
        slashable_findings=frozenset({"unavailable_artifact"}),
    )


def concretize_state(state: AbstractMarketState) -> BountyState:
    submissions: tuple[SubmissionState, ...] = ()
    if state.submission != "None":
        status = SubmissionStatus[state.submission.upper()]
        submissions = (
            SubmissionState(
                submission_id=SUBMISSION_ID,
                submitter_ref=SUBMITTER_REF,
                recipe_ref=RECIPE_REF,
                verifier_ref=VERIFIER_REF,
                evidence_refs=(EVIDENCE_REF,),
                artifact_refs=(ARTIFACT_REF,),
                submitted_at=5,
                status=status,
                bond_locked=Amount(state.bond_atoms),
                verifier_receipt_ref=None if status is SubmissionStatus.PENDING else VERIFIER_RECEIPT_REF,
            ),
        )
    challenges: tuple[ChallengeState, ...] = ()
    if state.challenge != "None":
        status = ChallengeStatus[state.challenge.upper()]
        challenges = (
            ChallengeState(
                challenge_id=CHALLENGE_ID,
                submission_id=SUBMISSION_ID,
                challenger_ref=CHALLENGER_REF,
                finding_kind="unavailable_artifact",
                evidence_refs=(CHALLENGE_EVIDENCE_REF,),
                opened_at=15,
                status=status,
                deposit_locked=Amount(state.deposit_atoms),
                verifier_receipt_ref=None if status is ChallengeStatus.OPEN else CHALLENGE_RECEIPT_REF,
            ),
        )
    phase = BountyPhase[state.phase.upper()]
    payable = (SUBMISSION_ID,) if phase in {BountyPhase.PAYABLE, BountyPhase.SETTLED} else ()
    settlement_ref = SETTLEMENT_REF if phase is BountyPhase.SETTLED else None
    concrete = BountyState(
        terms=_terms(),
        phase=phase,
        escrow_locked=Amount(state.escrow_atoms),
        submissions=submissions,
        challenges=challenges,
        payable_submission_ids=payable,
        settlement_ref=settlement_ref,
        processed_command_ids=frozenset(),
    )
    if bounty_state_violations(concrete):
        raise ValueError("concretized market state violates runtime invariants")
    return concrete


def _now(state: AbstractMarketState) -> int:
    if state.challenge_window_closed:
        return CHALLENGE_DEADLINE_EPOCH_S + 1
    if state.deadline_closed:
        return DEADLINE_EPOCH_S + 1
    return DEADLINE_EPOCH_S - 1


def concretize_command(kind: str, state: AbstractMarketState) -> MarketCommand:
    now = _now(state)
    if kind == "open_bounty":
        return OpenBounty("esso-open", SPONSOR_REF, Amount(REWARD_ATOMS), now)
    if kind == "submit_candidate":
        return SubmitCandidate(
            "esso-submit",
            SUBMISSION_ID,
            SUBMITTER_REF,
            RECIPE_REF,
            VERIFIER_REF,
            (EVIDENCE_REF,),
            (ARTIFACT_REF,),
            Amount(BOND_ATOMS),
            now,
        )
    if kind == "verify_accept":
        return VerifySubmission("esso-verify-accept", SUBMISSION_ID, VERIFIER_REF, VERIFIER_RECEIPT_REF, True, now)
    if kind == "verify_reject":
        return VerifySubmission("esso-verify-reject", SUBMISSION_ID, VERIFIER_REF, VERIFIER_RECEIPT_REF, False, now)
    if kind == "open_challenge":
        return OpenChallenge(
            "esso-open-challenge",
            CHALLENGE_ID,
            SUBMISSION_ID,
            CHALLENGER_REF,
            "unavailable_artifact",
            (CHALLENGE_EVIDENCE_REF,),
            Amount(DEPOSIT_ATOMS),
            now,
        )
    if kind == "resolve_upheld":
        return ResolveChallenge(
            "esso-resolve-upheld", CHALLENGE_ID, VERIFIER_REF, CHALLENGE_RECEIPT_REF, True, now
        )
    if kind == "resolve_rejected":
        return ResolveChallenge(
            "esso-resolve-rejected", CHALLENGE_ID, VERIFIER_REF, CHALLENGE_RECEIPT_REF, False, now
        )
    if kind == "advance":
        return AdvanceBounty("esso-advance", now)
    if kind == "settle":
        return SettleBounty(
            "esso-settle",
            SETTLEMENT_REF,
            (Payout(SUBMITTER_REF, SUBMISSION_ID, Amount(REWARD_ATOMS)),),
            now,
        )
    if kind == "cancel":
        return CancelBounty("esso-cancel", SPONSOR_REF, now)
    raise ValueError(f"command kind {kind!r} is context-only or unknown")


def _event_name(event_kind: str) -> str:
    mapping = {
        "bounty_opened": "EventOpened",
        "candidate_submitted": "EventSubmitted",
        "submission_verified": "EventVerified",
        "submission_rejected": "EventVerifierRejected",
        "challenge_opened": "EventChallengeOpened",
        "challenge_upheld": "EventChallengeUpheld",
        "challenge_rejected": "EventChallengeRejected",
        "bounty_payable": "EventPayable",
        "bounty_expired": "EventExpired",
        "bounty_settled": "EventSettled",
        "bounty_canceled": "EventCanceled",
    }
    return mapping[event_kind]


def _effect_deltas(effects: tuple[MarketEffect, ...]) -> dict[str, int]:
    deltas = {field: 0 for field in _COUNTER_FIELDS}
    mapping = {
        "payout": "payout_atoms",
        "refund_escrow": "escrow_refund_atoms",
        "refund_submission_bond": "bond_refund_atoms",
        "slash_submission_bond": "bond_slashed_atoms",
        "refund_challenge_deposit": "deposit_refund_atoms",
        "slash_challenge_deposit": "deposit_slashed_atoms",
    }
    for effect in effects:
        field = mapping.get(effect.kind)
        if field is not None:
            deltas[field] += effect.amount.atoms
    return deltas


def abstract_concrete_state(
    state: BountyState,
    *,
    prior: AbstractMarketState,
    effects: tuple[MarketEffect, ...],
) -> AbstractMarketState:
    submission = "None" if not state.submissions else state.submissions[0].status.name.title()
    bond = 0 if not state.submissions else state.submissions[0].bond_locked.atoms
    challenge = "None" if not state.challenges else state.challenges[0].status.name.title()
    deposit = 0 if not state.challenges else state.challenges[0].deposit_locked.atoms
    deltas = _effect_deltas(effects)
    return AbstractMarketState(
        phase=state.phase.name.title(),
        escrow_atoms=state.escrow_locked.atoms,
        submission=submission,
        bond_atoms=bond,
        challenge=challenge,
        deposit_atoms=deposit,
        deadline_closed=prior.deadline_closed,
        challenge_window_closed=prior.challenge_window_closed,
        resolution_enabled=challenge == "Open",
        **{field: getattr(prior, field) + deltas[field] for field in _COUNTER_FIELDS},
    )


def _context_step(kind: str, state: AbstractMarketState) -> dict[str, Any]:
    if kind == "close_deadline":
        if state.deadline_closed:
            return _reject_result(state, "GuardFalse")
        post = AbstractMarketState(
            **{
                **thaw_json(state.as_json()),
                "deadline_closed": True,
            }
        )
        event = "EventDeadlineClosed"
    elif kind == "close_challenge_window":
        if not state.deadline_closed or state.challenge_window_closed:
            return _reject_result(state, "GuardFalse")
        post = AbstractMarketState(
            **{
                **thaw_json(state.as_json()),
                "challenge_window_closed": True,
            }
        )
        event = "EventWindowClosed"
    else:
        raise ValueError(f"not a context command: {kind}")
    command_hash = canonical_hash("esso-market-context-command/v1", {"kind": kind, "state": state.as_json()})
    state_hash = canonical_hash("esso-market-abstract-state/v1", post.as_json())
    effect_plan_hash = canonical_hash("esso-market-context-effects/v1", {"event": event})
    return {
        "schema": RESULT_SCHEMA,
        "abstraction_id": ABSTRACTION_ID,
        "decision_kind": "accept",
        "reason_code": None,
        "state": thaw_json(post.as_json()),
        "effects": {"decision": "DecisionAccept", "event": event, **{field: getattr(post, field) for field in _COUNTER_FIELDS}},
        "receipt": {
            "command_hash": command_hash,
            "state_hash": state_hash,
            "effect_plan_hash": effect_plan_hash,
            "event_kind": event,
            "previous_phase": state.phase,
            "next_phase": post.phase,
        },
        "state_violations": [],
    }


def _reject_result(state: AbstractMarketState, reason: str) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "abstraction_id": ABSTRACTION_ID,
        "decision_kind": "reject",
        "reason_code": reason,
        "state": thaw_json(state.as_json()),
        "effects": {"decision": "DecisionReject", "event": "EventRejected", **{field: getattr(state, field) for field in _COUNTER_FIELDS}},
        "receipt": None,
        "state_violations": [],
    }


def step_document(document: Mapping[str, Any]) -> dict[str, Any]:
    if type(document) is not dict or set(document) != {"schema", "abstraction_id", "state", "command"}:
        raise ValueError("input document fields differ")
    if document["schema"] != SCHEMA or document["abstraction_id"] != ABSTRACTION_ID:
        raise ValueError("input schema or abstraction_id differs")
    raw_state = document["state"]
    raw_command = document["command"]
    if type(raw_state) is not dict or type(raw_command) is not dict or set(raw_command) != {"kind"}:
        raise ValueError("state and command must be exact objects")
    kind = raw_command["kind"]
    if type(kind) is not str or kind not in _COMMAND_KINDS:
        raise ValueError("unsupported command kind")
    state = AbstractMarketState.from_mapping(raw_state)
    if kind in {"close_deadline", "close_challenge_window"}:
        return _context_step(kind, state)

    concrete = concretize_state(state)
    decision = apply_market_command(concrete, concretize_command(kind, state), _policy())
    if isinstance(decision, Reject):
        return _reject_result(state, decision.code)
    effects = decision.effects
    post = abstract_concrete_state(decision.next_state, prior=state, effects=effects)
    violations = abstract_state_violations(post)
    receipt = decision.receipt
    return {
        "schema": RESULT_SCHEMA,
        "abstraction_id": ABSTRACTION_ID,
        "decision_kind": "accept" if isinstance(decision, Accept) else "committed_failure",
        "reason_code": None if isinstance(decision, Accept) else decision.code,
        "state": thaw_json(post.as_json()),
        "effects": {
            "decision": "DecisionAccept" if isinstance(decision, Accept) else "DecisionCommittedFailure",
            "event": _event_name(receipt.event_kind),
            **{field: getattr(post, field) for field in _COUNTER_FIELDS},
        },
        "receipt": {
            "command_hash": receipt.command_hash,
            "state_hash": receipt.state_hash,
            "effect_plan_hash": receipt.effect_plan_hash,
            "event_kind": receipt.event_kind,
            "previous_phase": receipt.previous_phase.value,
            "next_phase": receipt.next_phase.value,
        },
        "state_violations": list(violations),
    }


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"duplicate JSON key {key!r}")
        output[key] = value
    return output


def _reject_float(value: str) -> NoReturn:
    raise ValueError(f"floating-point JSON forbidden: {value}")


def _reject_constant(value: str) -> NoReturn:
    raise ValueError(f"JSON constant forbidden: {value}")


def _parse_canonical_line(line: bytes) -> dict[str, Any]:
    text = line.decode("utf-8", errors="strict")
    document = json.loads(
        text,
        object_pairs_hook=_strict_pairs,
        parse_float=_reject_float,
        parse_constant=_reject_constant,
    )
    if type(document) is not dict:
        raise ValueError("input must be a JSON object")
    if canonical_json_bytes(document).rstrip(b"\n") != line:
        raise ValueError("input must use PopperPad canonical JSON")
    return document


def _respond_line(line: bytes) -> bytes:
    if not line or b"\n" in line or b"\r" in line:
        raise ValueError("expected one non-empty canonical JSON line")
    return canonical_json_bytes(step_document(_parse_canonical_line(line)))


def main() -> int:
    arguments = tuple(sys.argv[1:])
    if arguments == ("--json-lines",):
        for raw_line in sys.stdin.buffer:
            line = raw_line.rstrip(b"\n")
            if line.endswith(b"\r"):
                raise SystemExit("CRLF input is not canonical")
            try:
                response = _respond_line(line)
            except Exception as error:
                raise SystemExit(f"{type(error).__name__}: {error}") from error
            sys.stdout.buffer.write(response)
            sys.stdout.buffer.flush()
        return 0
    if arguments:
        raise SystemExit("supported arguments: --json-lines")

    payload = sys.stdin.buffer.read()
    lines = payload.splitlines()
    if len(lines) != 1:
        raise SystemExit("expected exactly one canonical JSON line")
    try:
        response = _respond_line(lines[0])
    except Exception as error:
        raise SystemExit(f"{type(error).__name__}: {error}") from error
    sys.stdout.buffer.write(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
