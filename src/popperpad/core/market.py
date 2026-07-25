from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import ClassVar, TypeAlias

from .codec import canonical_hash
from .result import Accept, CommittedFailure, Reject
from .values import Amount, ClosedStrEnum, DeeplyImmutable, FrozenDict, JsonValue, freeze_json


_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")


class BountyPhase(ClosedStrEnum):
    __slots__ = ()

    DRAFT: ClassVar[BountyPhase]
    OPEN: ClassVar[BountyPhase]
    PAYABLE: ClassVar[BountyPhase]
    SETTLED: ClassVar[BountyPhase]
    EXPIRED: ClassVar[BountyPhase]
    CANCELED: ClassVar[BountyPhase]
    _symbols = (
        ("DRAFT", "draft"),
        ("OPEN", "open"),
        ("PAYABLE", "payable"),
        ("SETTLED", "settled"),
        ("EXPIRED", "expired"),
        ("CANCELED", "canceled"),
    )


class SubmissionStatus(ClosedStrEnum):
    __slots__ = ()

    PENDING: ClassVar[SubmissionStatus]
    VERIFIED: ClassVar[SubmissionStatus]
    REJECTED: ClassVar[SubmissionStatus]
    _symbols = (
        ("PENDING", "pending"),
        ("VERIFIED", "verified"),
        ("REJECTED", "rejected"),
    )


class ChallengeStatus(ClosedStrEnum):
    __slots__ = ()

    OPEN: ClassVar[ChallengeStatus]
    UPHELD: ClassVar[ChallengeStatus]
    REJECTED: ClassVar[ChallengeStatus]
    _symbols = (
        ("OPEN", "open"),
        ("UPHELD", "upheld"),
        ("REJECTED", "rejected"),
    )


@dataclass(frozen=True, slots=True)
class BountyTerms(DeeplyImmutable):
    bounty_id: str
    sponsor_ref: str
    claim_ref: str
    context_ref: str | None
    reward: Amount
    minimum_submission_bond: Amount
    deadline_epoch_s: int
    challenge_window_seconds: int
    accepted_recipe_refs: frozenset[str]
    accepted_verifier_refs: frozenset[str]

    def __post_init__(self) -> None:
        if not _valid_id(self.bounty_id):
            raise ValueError("invalid bounty_id")
        if not self.sponsor_ref:
            raise ValueError("sponsor_ref must be non-empty")
        if not _valid_ref(self.claim_ref):
            raise ValueError("claim_ref must be sha256:<64hex>")
        if self.context_ref is not None and not _valid_ref(self.context_ref):
            raise ValueError("context_ref must be null or sha256:<64hex>")
        if self.reward.atoms <= 0:
            raise ValueError("reward must be positive")
        if self.deadline_epoch_s < 0 or self.challenge_window_seconds < 0:
            raise ValueError("deadline/window values must be non-negative")
        if not self.accepted_recipe_refs or not all(_valid_ref(ref) for ref in self.accepted_recipe_refs):
            raise ValueError("accepted_recipe_refs must be non-empty valid refs")
        if not self.accepted_verifier_refs or not all(_valid_ref(ref) for ref in self.accepted_verifier_refs):
            raise ValueError("accepted_verifier_refs must be non-empty valid refs")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class SubmissionState(DeeplyImmutable):
    submission_id: str
    submitter_ref: str
    recipe_ref: str
    verifier_ref: str
    evidence_refs: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    submitted_at: int
    status: SubmissionStatus
    bond_locked: Amount
    verifier_receipt_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ChallengeState(DeeplyImmutable):
    challenge_id: str
    submission_id: str
    challenger_ref: str
    finding_kind: str
    evidence_refs: tuple[str, ...]
    opened_at: int
    status: ChallengeStatus
    deposit_locked: Amount
    verifier_receipt_ref: str | None = None


@dataclass(frozen=True, slots=True)
class BountyState(DeeplyImmutable):
    terms: BountyTerms
    phase: BountyPhase = BountyPhase.DRAFT
    escrow_locked: Amount = Amount(0)
    submissions: tuple[SubmissionState, ...] = ()
    challenges: tuple[ChallengeState, ...] = ()
    payable_submission_ids: tuple[str, ...] = ()
    settlement_ref: str | None = None
    processed_command_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class MarketPolicy(DeeplyImmutable):
    minimum_bounty: Amount
    minimum_submission_bond: Amount
    minimum_challenge_deposit: Amount
    slashable_findings: frozenset[str]
    treasury_ref: str = "protocol:treasury"
    challenge_resolution_seconds: int = 86_400

    def __post_init__(self) -> None:
        if not self.slashable_findings:
            raise ValueError("slashable_findings must be non-empty")
        if not self.treasury_ref:
            raise ValueError("treasury_ref must be non-empty")
        DeeplyImmutable.__post_init__(self)


@dataclass(frozen=True, slots=True)
class MarketEffect(DeeplyImmutable):
    kind: str
    account_ref: str
    amount: Amount
    subject_ref: str
    metadata: FrozenDict[JsonValue] = FrozenDict()

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "kind": self.kind,
                "account_ref": self.account_ref,
                "amount_atoms": self.amount.atoms,
                "subject_ref": self.subject_ref,
                "metadata": self.metadata,
            }
        )
        assert isinstance(value, FrozenDict)
        return value


@dataclass(frozen=True, slots=True)
class TransitionReceipt(DeeplyImmutable):
    version: str
    bounty_id: str
    command_id: str
    event_kind: str
    occurred_at: int
    previous_phase: BountyPhase
    next_phase: BountyPhase
    command_hash: str
    state_hash: str
    effect_plan_hash: str


@dataclass(frozen=True, slots=True)
class OpenBounty(DeeplyImmutable):
    command_id: str
    sponsor_ref: str
    funded: Amount
    now_epoch_s: int


@dataclass(frozen=True, slots=True)
class SubmitCandidate(DeeplyImmutable):
    command_id: str
    submission_id: str
    submitter_ref: str
    recipe_ref: str
    verifier_ref: str
    evidence_refs: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    bond: Amount
    now_epoch_s: int


@dataclass(frozen=True, slots=True)
class VerifySubmission(DeeplyImmutable):
    command_id: str
    submission_id: str
    verifier_ref: str
    verifier_receipt_ref: str
    accepted: bool
    now_epoch_s: int


@dataclass(frozen=True, slots=True)
class OpenChallenge(DeeplyImmutable):
    command_id: str
    challenge_id: str
    submission_id: str
    challenger_ref: str
    finding_kind: str
    evidence_refs: tuple[str, ...]
    deposit: Amount
    now_epoch_s: int


@dataclass(frozen=True, slots=True)
class ResolveChallenge(DeeplyImmutable):
    command_id: str
    challenge_id: str
    verifier_ref: str
    verifier_receipt_ref: str
    upheld: bool
    now_epoch_s: int


@dataclass(frozen=True, slots=True)
class AdvanceBounty(DeeplyImmutable):
    command_id: str
    now_epoch_s: int


@dataclass(frozen=True, slots=True)
class Payout(DeeplyImmutable):
    recipient_ref: str
    submission_id: str
    amount: Amount


@dataclass(frozen=True, slots=True)
class SettleBounty(DeeplyImmutable):
    command_id: str
    settlement_ref: str
    payouts: tuple[Payout, ...]
    now_epoch_s: int


@dataclass(frozen=True, slots=True)
class CancelBounty(DeeplyImmutable):
    command_id: str
    sponsor_ref: str
    now_epoch_s: int


MarketCommand: TypeAlias = (
    OpenBounty
    | SubmitCandidate
    | VerifySubmission
    | OpenChallenge
    | ResolveChallenge
    | AdvanceBounty
    | SettleBounty
    | CancelBounty
)
MarketDecision: TypeAlias = (
    Accept[BountyState, MarketEffect, TransitionReceipt]
    | Reject
    | CommittedFailure[BountyState, MarketEffect, TransitionReceipt]
)


# This order is normative and tested. Earlier classes of invalidity always win.
REJECTION_PRECEDENCE = (
    "INVALID_STATE",
    "INVALID_POLICY",
    "INVALID_COMMAND",
    "DUPLICATE_COMMAND",
    "WRONG_PHASE",
    "TIME_WINDOW",
    "DUPLICATE_ENTITY",
    "UNKNOWN_ENTITY",
    "POLICY_MISMATCH",
    "MISSING_EVIDENCE",
    "INSUFFICIENT_AMOUNT",
    "CONSERVATION_FAILURE",
)


def initial_bounty(terms: BountyTerms) -> BountyState:
    return BountyState(terms=terms)


def apply_market_command(
    state: BountyState,
    command: MarketCommand,
    policy: MarketPolicy,
) -> MarketDecision:
    """Apply one total deterministic market transition over immutable values."""

    invalid_state = _validate_market_state(state)
    if invalid_state is not None:
        return _reject("INVALID_STATE", "state", invalid_state)
    invalid_policy = _validate_market_policy(policy)
    if invalid_policy is not None:
        return _reject("INVALID_POLICY", "policy", invalid_policy)
    if type(command) not in (
        OpenBounty,
        SubmitCandidate,
        VerifySubmission,
        OpenChallenge,
        ResolveChallenge,
        AdvanceBounty,
        SettleBounty,
        CancelBounty,
    ):
        return _reject("INVALID_COMMAND", "type", type(command).__name__)
    invalid = _validate_common_command(command)
    if invalid is not None:
        return invalid
    if command.command_id in state.processed_command_ids:
        return _reject("DUPLICATE_COMMAND", "command_id", command.command_id)

    if isinstance(command, OpenBounty):
        return _open_bounty(state, command, policy)
    if isinstance(command, SubmitCandidate):
        return _submit_candidate(state, command, policy)
    if isinstance(command, VerifySubmission):
        return _verify_submission(state, command)
    if isinstance(command, OpenChallenge):
        return _open_challenge(state, command, policy)
    if isinstance(command, ResolveChallenge):
        return _resolve_challenge(state, command, policy)
    if isinstance(command, AdvanceBounty):
        return _advance_bounty(state, command, policy)
    if isinstance(command, SettleBounty):
        return _settle_bounty(state, command)
    if isinstance(command, CancelBounty):
        return _cancel_bounty(state, command)
    return _reject("INVALID_COMMAND", "type", type(command).__name__)


def _open_bounty(state: BountyState, command: OpenBounty, policy: MarketPolicy) -> MarketDecision:
    if state.phase is not BountyPhase.DRAFT:
        return _reject("WRONG_PHASE", "phase", state.phase.value)
    if command.now_epoch_s >= state.terms.deadline_epoch_s:
        return _reject("TIME_WINDOW", "deadline", "bounty must open before deadline")
    if command.sponsor_ref != state.terms.sponsor_ref:
        return _reject("POLICY_MISMATCH", "sponsor_ref", command.sponsor_ref)
    required = max(state.terms.reward.atoms, policy.minimum_bounty.atoms)
    if command.funded.atoms != required:
        return _reject("INSUFFICIENT_AMOUNT", "funded", f"must equal {required} atoms")

    effect = _effect(
        "lock_escrow",
        command.sponsor_ref,
        command.funded,
        state.terms.bounty_id,
    )
    next_state = replace(
        state,
        phase=BountyPhase.OPEN,
        escrow_locked=command.funded,
        processed_command_ids=state.processed_command_ids | frozenset({command.command_id}),
    )
    return _accept(state, next_state, command, "bounty_opened", (effect,))


def _submit_candidate(
    state: BountyState,
    command: SubmitCandidate,
    policy: MarketPolicy,
) -> MarketDecision:
    if not _valid_id(command.submission_id) or not command.submitter_ref:
        return _reject("INVALID_COMMAND", "submission", command.submission_id)
    if not (_valid_ref(command.recipe_ref) and _valid_ref(command.verifier_ref)):
        return _reject("INVALID_COMMAND", "recipe_or_verifier_ref", "invalid ref")
    if not all(_valid_ref(ref) for ref in (*command.evidence_refs, *command.artifact_refs)):
        return _reject("INVALID_COMMAND", "evidence_or_artifact_ref", "invalid ref")
    if state.phase is not BountyPhase.OPEN:
        return _reject("WRONG_PHASE", "phase", state.phase.value)
    if command.now_epoch_s > state.terms.deadline_epoch_s:
        return _reject("TIME_WINDOW", "deadline", "submission arrived after deadline")
    if _submission(state, command.submission_id) is not None:
        return _reject("DUPLICATE_ENTITY", "submission_id", command.submission_id)
    if command.recipe_ref not in state.terms.accepted_recipe_refs:
        return _reject("POLICY_MISMATCH", "recipe_ref", command.recipe_ref)
    if command.verifier_ref not in state.terms.accepted_verifier_refs:
        return _reject("POLICY_MISMATCH", "verifier_ref", command.verifier_ref)
    if not command.evidence_refs:
        return _reject("MISSING_EVIDENCE", "evidence_refs", "must be non-empty")
    required = max(state.terms.minimum_submission_bond.atoms, policy.minimum_submission_bond.atoms)
    if command.bond.atoms < required:
        return _reject("INSUFFICIENT_AMOUNT", "bond", f"minimum is {required} atoms")

    submission = SubmissionState(
        submission_id=command.submission_id,
        submitter_ref=command.submitter_ref,
        recipe_ref=command.recipe_ref,
        verifier_ref=command.verifier_ref,
        evidence_refs=tuple(command.evidence_refs),
        artifact_refs=tuple(command.artifact_refs),
        submitted_at=command.now_epoch_s,
        status=SubmissionStatus.PENDING,
        bond_locked=command.bond,
    )
    effect = _effect("lock_submission_bond", command.submitter_ref, command.bond, command.submission_id)
    next_state = replace(
        state,
        submissions=(*state.submissions, submission),
        processed_command_ids=state.processed_command_ids | frozenset({command.command_id}),
    )
    return _accept(state, next_state, command, "candidate_submitted", (effect,))


def _verify_submission(state: BountyState, command: VerifySubmission) -> MarketDecision:
    if not (_valid_id(command.submission_id) and _valid_ref(command.verifier_ref)):
        return _reject("INVALID_COMMAND", "submission_or_verifier", "invalid")
    if not _valid_ref(command.verifier_receipt_ref):
        return _reject("INVALID_COMMAND", "verifier_receipt_ref", command.verifier_receipt_ref)
    if state.phase is not BountyPhase.OPEN:
        return _reject("WRONG_PHASE", "phase", state.phase.value)
    if command.now_epoch_s > _challenge_deadline(state):
        return _reject("TIME_WINDOW", "challenge_deadline", "verification arrived too late")
    submission = _submission(state, command.submission_id)
    if submission is None:
        return _reject("UNKNOWN_ENTITY", "submission_id", command.submission_id)
    if submission.status is not SubmissionStatus.PENDING:
        return _reject("POLICY_MISMATCH", "submission_status", submission.status.value)
    if command.verifier_ref != submission.verifier_ref:
        return _reject("POLICY_MISMATCH", "verifier_ref", command.verifier_ref)

    next_submission = replace(
        submission,
        status=SubmissionStatus.VERIFIED if command.accepted else SubmissionStatus.REJECTED,
        bond_locked=submission.bond_locked if command.accepted else Amount.zero(),
        verifier_receipt_ref=command.verifier_receipt_ref,
    )
    next_state = replace(
        state,
        submissions=_replace_submission(state.submissions, next_submission),
        processed_command_ids=state.processed_command_ids | frozenset({command.command_id}),
    )
    if command.accepted:
        return _accept(state, next_state, command, "submission_verified", ())

    effect = _effect(
        "refund_submission_bond",
        submission.submitter_ref,
        submission.bond_locked,
        submission.submission_id,
        reason="honest_verifier_rejection",
    )
    return _committed_failure(
        state,
        next_state,
        command,
        event_kind="submission_rejected",
        failure_code="VERIFIER_REJECTED",
        effects=(effect,),
    )


def _open_challenge(
    state: BountyState,
    command: OpenChallenge,
    policy: MarketPolicy,
) -> MarketDecision:
    if not (_valid_id(command.challenge_id) and _valid_id(command.submission_id)):
        return _reject("INVALID_COMMAND", "challenge_or_submission_id", "invalid")
    if not command.challenger_ref or not command.finding_kind:
        return _reject("INVALID_COMMAND", "challenger_or_finding", "must be non-empty")
    if not all(_valid_ref(ref) for ref in command.evidence_refs):
        return _reject("INVALID_COMMAND", "evidence_refs", "invalid ref")
    if state.phase is not BountyPhase.OPEN:
        return _reject("WRONG_PHASE", "phase", state.phase.value)
    if command.now_epoch_s > _challenge_deadline(state):
        return _reject("TIME_WINDOW", "challenge_deadline", "challenge arrived too late")
    if _challenge(state, command.challenge_id) is not None:
        return _reject("DUPLICATE_ENTITY", "challenge_id", command.challenge_id)
    submission = _submission(state, command.submission_id)
    if submission is None:
        return _reject("UNKNOWN_ENTITY", "submission_id", command.submission_id)
    if submission.status is not SubmissionStatus.VERIFIED:
        return _reject("POLICY_MISMATCH", "submission_status", submission.status.value)
    if any(
        challenge.submission_id == command.submission_id and challenge.status is ChallengeStatus.OPEN
        for challenge in state.challenges
    ):
        return _reject("POLICY_MISMATCH", "submission_id", "already has an open challenge")
    if command.finding_kind not in policy.slashable_findings:
        return _reject("POLICY_MISMATCH", "finding_kind", command.finding_kind)
    if not command.evidence_refs:
        return _reject("MISSING_EVIDENCE", "evidence_refs", "must be non-empty")
    if command.deposit.atoms < policy.minimum_challenge_deposit.atoms:
        return _reject(
            "INSUFFICIENT_AMOUNT",
            "deposit",
            f"minimum is {policy.minimum_challenge_deposit.atoms} atoms",
        )

    challenge = ChallengeState(
        challenge_id=command.challenge_id,
        submission_id=command.submission_id,
        challenger_ref=command.challenger_ref,
        finding_kind=command.finding_kind,
        evidence_refs=tuple(command.evidence_refs),
        opened_at=command.now_epoch_s,
        status=ChallengeStatus.OPEN,
        deposit_locked=command.deposit,
    )
    effect = _effect(
        "lock_challenge_deposit",
        command.challenger_ref,
        command.deposit,
        command.challenge_id,
    )
    next_state = replace(
        state,
        challenges=(*state.challenges, challenge),
        processed_command_ids=state.processed_command_ids | frozenset({command.command_id}),
    )
    return _accept(state, next_state, command, "challenge_opened", (effect,))


def _resolve_challenge(
    state: BountyState,
    command: ResolveChallenge,
    policy: MarketPolicy,
) -> MarketDecision:
    if not (_valid_id(command.challenge_id) and _valid_ref(command.verifier_ref)):
        return _reject("INVALID_COMMAND", "challenge_or_verifier", "invalid")
    if not _valid_ref(command.verifier_receipt_ref):
        return _reject("INVALID_COMMAND", "verifier_receipt_ref", command.verifier_receipt_ref)
    if state.phase is not BountyPhase.OPEN:
        return _reject("WRONG_PHASE", "phase", state.phase.value)
    # The challenge deadline limits filing. A timely open challenge remains
    # adjudicable afterward so it cannot permanently deadlock the bounty.
    challenge = _challenge(state, command.challenge_id)
    if challenge is None:
        return _reject("UNKNOWN_ENTITY", "challenge_id", command.challenge_id)
    if challenge.status is not ChallengeStatus.OPEN:
        return _reject("POLICY_MISMATCH", "challenge_status", challenge.status.value)
    if command.now_epoch_s > _resolution_deadline(state, challenge, policy):
        return _reject("TIME_WINDOW", "resolution_deadline", "challenge adjudication timed out")
    if command.verifier_ref not in state.terms.accepted_verifier_refs:
        return _reject("POLICY_MISMATCH", "verifier_ref", command.verifier_ref)
    submission = _submission(state, challenge.submission_id)
    if submission is None:
        return _reject("UNKNOWN_ENTITY", "submission_id", challenge.submission_id)

    next_challenge = replace(
        challenge,
        status=ChallengeStatus.UPHELD if command.upheld else ChallengeStatus.REJECTED,
        deposit_locked=Amount.zero(),
        verifier_receipt_ref=command.verifier_receipt_ref,
    )
    effects: list[MarketEffect] = []
    if command.upheld:
        next_submission = replace(
            submission,
            status=SubmissionStatus.REJECTED,
            bond_locked=Amount.zero(),
        )
        effects.append(
            _effect(
                "refund_challenge_deposit",
                challenge.challenger_ref,
                challenge.deposit_locked,
                challenge.challenge_id,
            )
        )
        effects.append(
            _effect(
                "slash_submission_bond",
                policy.treasury_ref,
                submission.bond_locked,
                submission.submission_id,
                finding_kind=challenge.finding_kind,
            )
        )
        next_state = replace(
            state,
            submissions=_replace_submission(state.submissions, next_submission),
            challenges=_replace_challenge(state.challenges, next_challenge),
            processed_command_ids=state.processed_command_ids | frozenset({command.command_id}),
        )
        return _accept(state, next_state, command, "challenge_upheld", tuple(effects))

    effects.append(
        _effect(
            "slash_challenge_deposit",
            policy.treasury_ref,
            challenge.deposit_locked,
            challenge.challenge_id,
            finding_kind=challenge.finding_kind,
        )
    )
    next_state = replace(
        state,
        challenges=_replace_challenge(state.challenges, next_challenge),
        processed_command_ids=state.processed_command_ids | frozenset({command.command_id}),
    )
    return _committed_failure(
        state,
        next_state,
        command,
        event_kind="challenge_rejected",
        failure_code="CHALLENGE_REJECTED",
        effects=tuple(effects),
    )


def _advance_bounty(
    state: BountyState,
    command: AdvanceBounty,
    policy: MarketPolicy,
) -> MarketDecision:
    if state.phase is not BountyPhase.OPEN:
        return _reject("WRONG_PHASE", "phase", state.phase.value)
    if command.now_epoch_s <= _challenge_deadline(state):
        return _reject("TIME_WINDOW", "challenge_deadline", "window is still open")
    open_challenges = tuple(
        challenge for challenge in state.challenges if challenge.status is ChallengeStatus.OPEN
    )
    if any(
        command.now_epoch_s <= _resolution_deadline(state, challenge, policy)
        for challenge in open_challenges
    ):
        return _reject("POLICY_MISMATCH", "challenges", "challenge adjudication is still open")

    next_challenges = state.challenges
    effects: list[MarketEffect] = []
    for challenge in open_challenges:
        timed_out = replace(
            challenge,
            status=ChallengeStatus.REJECTED,
            deposit_locked=Amount.zero(),
        )
        next_challenges = _replace_challenge(next_challenges, timed_out)
        effects.append(
            _effect(
                "slash_challenge_deposit",
                policy.treasury_ref,
                challenge.deposit_locked,
                challenge.challenge_id,
                finding_kind=challenge.finding_kind,
                reason="resolution_timeout",
            )
        )

    eligible = tuple(
        submission.submission_id
        for submission in sorted(state.submissions, key=lambda value: (value.submitted_at, value.submission_id))
        if submission.status is SubmissionStatus.VERIFIED
    )
    if eligible:
        next_state = replace(
            state,
            phase=BountyPhase.PAYABLE,
            challenges=next_challenges,
            payable_submission_ids=eligible,
            processed_command_ids=state.processed_command_ids | frozenset({command.command_id}),
        )
        return _accept(state, next_state, command, "bounty_payable", tuple(effects))

    effects.append(
        _effect(
            "refund_escrow",
            state.terms.sponsor_ref,
            state.escrow_locked,
            state.terms.bounty_id,
            reason="no_payable_submission",
        )
    )
    next_submissions: list[SubmissionState] = []
    for submission in state.submissions:
        if submission.bond_locked.atoms > 0:
            effects.append(
                _effect(
                    "refund_submission_bond",
                    submission.submitter_ref,
                    submission.bond_locked,
                    submission.submission_id,
                    reason="bounty_expired",
                )
            )
            next_submissions.append(replace(submission, bond_locked=Amount.zero()))
        else:
            next_submissions.append(submission)
    next_state = replace(
        state,
        phase=BountyPhase.EXPIRED,
        escrow_locked=Amount.zero(),
        submissions=tuple(next_submissions),
        challenges=next_challenges,
        processed_command_ids=state.processed_command_ids | frozenset({command.command_id}),
    )
    return _committed_failure(
        state,
        next_state,
        command,
        event_kind="bounty_expired",
        failure_code="NO_PAYABLE_SUBMISSION",
        effects=tuple(effects),
    )


def _settle_bounty(state: BountyState, command: SettleBounty) -> MarketDecision:
    if not command.settlement_ref:
        return _reject("INVALID_COMMAND", "settlement_ref", "must be non-empty")
    if any(not _valid_id(payout.submission_id) or not payout.recipient_ref for payout in command.payouts):
        return _reject("INVALID_COMMAND", "payout", "invalid recipient or submission")
    if state.phase is not BountyPhase.PAYABLE:
        return _reject("WRONG_PHASE", "phase", state.phase.value)
    if not command.payouts:
        return _reject("MISSING_EVIDENCE", "payouts", "must be non-empty")

    eligible = {submission_id: _submission(state, submission_id) for submission_id in state.payable_submission_ids}
    seen_submission_ids: set[str] = set()
    payout_total = 0
    for payout in command.payouts:
        submission = eligible.get(payout.submission_id)
        if submission is None:
            return _reject("UNKNOWN_ENTITY", "submission_id", payout.submission_id)
        if payout.submission_id in seen_submission_ids:
            return _reject("DUPLICATE_ENTITY", "submission_id", payout.submission_id)
        seen_submission_ids.add(payout.submission_id)
        if payout.recipient_ref != submission.submitter_ref:
            return _reject("POLICY_MISMATCH", "recipient_ref", payout.recipient_ref)
        payout_total += payout.amount.atoms
    if payout_total != state.escrow_locked.atoms:
        return _reject(
            "CONSERVATION_FAILURE",
            "payouts",
            f"sum {payout_total} != escrow {state.escrow_locked.atoms}",
        )

    effects: list[MarketEffect] = [
        _effect("payout", payout.recipient_ref, payout.amount, payout.submission_id)
        for payout in command.payouts
    ]
    next_submissions: list[SubmissionState] = []
    for submission in state.submissions:
        if submission.bond_locked.atoms > 0:
            effects.append(
                _effect(
                    "refund_submission_bond",
                    submission.submitter_ref,
                    submission.bond_locked,
                    submission.submission_id,
                    reason="settlement_complete",
                )
            )
            next_submissions.append(replace(submission, bond_locked=Amount.zero()))
        else:
            next_submissions.append(submission)
    next_state = replace(
        state,
        phase=BountyPhase.SETTLED,
        escrow_locked=Amount.zero(),
        submissions=tuple(next_submissions),
        settlement_ref=command.settlement_ref,
        processed_command_ids=state.processed_command_ids | frozenset({command.command_id}),
    )
    return _accept(state, next_state, command, "bounty_settled", tuple(effects))


def _cancel_bounty(state: BountyState, command: CancelBounty) -> MarketDecision:
    if state.phase is not BountyPhase.OPEN:
        return _reject("WRONG_PHASE", "phase", state.phase.value)
    if command.now_epoch_s >= state.terms.deadline_epoch_s:
        return _reject("TIME_WINDOW", "deadline", "cannot cancel at or after deadline")
    if state.submissions or state.challenges:
        return _reject("POLICY_MISMATCH", "market_activity", "cannot cancel after activity")
    if command.sponsor_ref != state.terms.sponsor_ref:
        return _reject("POLICY_MISMATCH", "sponsor_ref", command.sponsor_ref)

    effect = _effect(
        "refund_escrow",
        state.terms.sponsor_ref,
        state.escrow_locked,
        state.terms.bounty_id,
        reason="sponsor_cancel_before_activity",
    )
    next_state = replace(
        state,
        phase=BountyPhase.CANCELED,
        escrow_locked=Amount.zero(),
        processed_command_ids=state.processed_command_ids | frozenset({command.command_id}),
    )
    return _accept(state, next_state, command, "bounty_canceled", (effect,))


def _validate_common_command(command: MarketCommand) -> Reject | None:
    if not _valid_id(command.command_id):
        return _reject("INVALID_COMMAND", "command_id", str(command.command_id))
    if (
        not isinstance(command.now_epoch_s, int)
        or isinstance(command.now_epoch_s, bool)
        or command.now_epoch_s < 0
    ):
        return _reject("INVALID_COMMAND", "now_epoch_s", str(command.now_epoch_s))
    if isinstance(command, OpenBounty):
        if not isinstance(command.sponsor_ref, str) or not isinstance(command.funded, Amount):
            return _reject("INVALID_COMMAND", "open_bounty", "invalid field type")
    elif isinstance(command, SubmitCandidate):
        if not all(
            (
                isinstance(command.submission_id, str),
                isinstance(command.submitter_ref, str),
                isinstance(command.recipe_ref, str),
                isinstance(command.verifier_ref, str),
                _is_ref_tuple(command.evidence_refs),
                _is_ref_tuple(command.artifact_refs),
                isinstance(command.bond, Amount),
            )
        ):
            return _reject("INVALID_COMMAND", "submit_candidate", "invalid field type")
    elif isinstance(command, VerifySubmission):
        if not all(
            (
                isinstance(command.submission_id, str),
                isinstance(command.verifier_ref, str),
                isinstance(command.verifier_receipt_ref, str),
                isinstance(command.accepted, bool),
            )
        ):
            return _reject("INVALID_COMMAND", "verify_submission", "invalid field type")
    elif isinstance(command, OpenChallenge):
        if not all(
            (
                isinstance(command.challenge_id, str),
                isinstance(command.submission_id, str),
                isinstance(command.challenger_ref, str),
                isinstance(command.finding_kind, str),
                _is_ref_tuple(command.evidence_refs),
                isinstance(command.deposit, Amount),
            )
        ):
            return _reject("INVALID_COMMAND", "open_challenge", "invalid field type")
    elif isinstance(command, ResolveChallenge):
        if not all(
            (
                isinstance(command.challenge_id, str),
                isinstance(command.verifier_ref, str),
                isinstance(command.verifier_receipt_ref, str),
                isinstance(command.upheld, bool),
            )
        ):
            return _reject("INVALID_COMMAND", "resolve_challenge", "invalid field type")
    elif isinstance(command, SettleBounty):
        if not isinstance(command.settlement_ref, str) or not isinstance(command.payouts, tuple):
            return _reject("INVALID_COMMAND", "settle_bounty", "invalid field type")
        if any(
            not isinstance(payout, Payout)
            or not isinstance(payout.recipient_ref, str)
            or not isinstance(payout.submission_id, str)
            or not isinstance(payout.amount, Amount)
            for payout in command.payouts
        ):
            return _reject("INVALID_COMMAND", "payout", "invalid field type")
    elif isinstance(command, CancelBounty) and not isinstance(command.sponsor_ref, str):
        return _reject("INVALID_COMMAND", "sponsor_ref", "invalid field type")
    return None


def _validate_market_state(value: object) -> str | None:
    from .market_invariants import market_state_violations

    violations = market_state_violations(value)
    return None if not violations else violations[0].render()


def _validate_market_policy(value: object) -> str | None:
    if type(value) is not MarketPolicy:
        return f"expected MarketPolicy, got {type(value).__name__}"
    if not all(
        type(amount) is Amount
        for amount in (
            value.minimum_bounty,
            value.minimum_submission_bond,
            value.minimum_challenge_deposit,
        )
    ):
        return "minimum amounts must be Amount values"
    if (
        not isinstance(value.slashable_findings, frozenset)
        or not value.slashable_findings
        or not all(
            isinstance(finding, str) and bool(finding)
            for finding in value.slashable_findings
        )
    ):
        return "slashable_findings must be a non-empty frozenset of strings"
    if not isinstance(value.treasury_ref, str) or not value.treasury_ref:
        return "treasury_ref must be a non-empty string"
    if not _is_non_negative_int(value.challenge_resolution_seconds):
        return "challenge_resolution_seconds must be a non-negative integer"
    return None


def _valid_submission_state(value: object) -> bool:
    return type(value) is SubmissionState and all(
        (
            _valid_id(value.submission_id),
            isinstance(value.submitter_ref, str) and bool(value.submitter_ref),
            _valid_ref(value.recipe_ref),
            _valid_ref(value.verifier_ref),
            _is_ref_tuple(value.evidence_refs),
            _is_ref_tuple(value.artifact_refs),
            _is_non_negative_int(value.submitted_at),
            type(value.status) is SubmissionStatus,
            type(value.bond_locked) is Amount,
            value.verifier_receipt_ref is None or _valid_ref(value.verifier_receipt_ref),
        )
    )


def _valid_challenge_state(value: object) -> bool:
    return type(value) is ChallengeState and all(
        (
            _valid_id(value.challenge_id),
            _valid_id(value.submission_id),
            isinstance(value.challenger_ref, str) and bool(value.challenger_ref),
            isinstance(value.finding_kind, str) and bool(value.finding_kind),
            _is_ref_tuple(value.evidence_refs),
            _is_non_negative_int(value.opened_at),
            type(value.status) is ChallengeStatus,
            type(value.deposit_locked) is Amount,
            value.verifier_receipt_ref is None or _valid_ref(value.verifier_receipt_ref),
        )
    )


def _is_ref_tuple(value: object) -> bool:
    return isinstance(value, tuple) and all(_valid_ref(item) for item in value)


def _is_ref_frozenset(value: object, *, non_empty: bool = False) -> bool:
    return (
        isinstance(value, frozenset)
        and (bool(value) or not non_empty)
        and all(_valid_ref(item) for item in value)
    )


def _is_id_tuple(value: object) -> bool:
    return isinstance(value, tuple) and all(_valid_id(item) for item in value)


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _accept(
    previous: BountyState,
    next_state: BountyState,
    command: MarketCommand,
    event_kind: str,
    effects: tuple[MarketEffect, ...],
) -> Accept[BountyState, MarketEffect, TransitionReceipt]:
    return Accept(
        next_state=next_state,
        effects=effects,
        receipt=_receipt(previous, next_state, command, event_kind, effects),
    )


def _committed_failure(
    previous: BountyState,
    next_state: BountyState,
    command: MarketCommand,
    *,
    event_kind: str,
    failure_code: str,
    effects: tuple[MarketEffect, ...],
) -> CommittedFailure[BountyState, MarketEffect, TransitionReceipt]:
    return CommittedFailure(
        code=failure_code,
        next_state=next_state,
        effects=effects,
        receipt=_receipt(previous, next_state, command, event_kind, effects),
    )


def _receipt(
    previous: BountyState,
    next_state: BountyState,
    command: MarketCommand,
    event_kind: str,
    effects: tuple[MarketEffect, ...],
) -> TransitionReceipt:
    command_hash = canonical_hash("market-command/v1", _command_json(command))
    state_hash = canonical_hash("market-state/v1", _state_json(next_state))
    effect_plan_hash = canonical_hash(
        "market-effects/v1",
        tuple(effect.as_json() for effect in effects),
    )
    return TransitionReceipt(
        version="popperpad/market-receipt/v1",
        bounty_id=next_state.terms.bounty_id,
        command_id=command.command_id,
        event_kind=event_kind,
        occurred_at=command.now_epoch_s,
        previous_phase=previous.phase,
        next_phase=next_state.phase,
        command_hash=command_hash,
        state_hash=state_hash,
        effect_plan_hash=effect_plan_hash,
    )


def _command_json(command: MarketCommand) -> FrozenDict[JsonValue]:
    if isinstance(command, OpenBounty):
        value = {
            "kind": "open_bounty",
            "command_id": command.command_id,
            "sponsor_ref": command.sponsor_ref,
            "funded_atoms": command.funded.atoms,
            "now_epoch_s": command.now_epoch_s,
        }
    elif isinstance(command, SubmitCandidate):
        value = {
            "kind": "submit_candidate",
            "command_id": command.command_id,
            "submission_id": command.submission_id,
            "submitter_ref": command.submitter_ref,
            "recipe_ref": command.recipe_ref,
            "verifier_ref": command.verifier_ref,
            "evidence_refs": command.evidence_refs,
            "artifact_refs": command.artifact_refs,
            "bond_atoms": command.bond.atoms,
            "now_epoch_s": command.now_epoch_s,
        }
    elif isinstance(command, VerifySubmission):
        value = {
            "kind": "verify_submission",
            "command_id": command.command_id,
            "submission_id": command.submission_id,
            "verifier_ref": command.verifier_ref,
            "verifier_receipt_ref": command.verifier_receipt_ref,
            "accepted": command.accepted,
            "now_epoch_s": command.now_epoch_s,
        }
    elif isinstance(command, OpenChallenge):
        value = {
            "kind": "open_challenge",
            "command_id": command.command_id,
            "challenge_id": command.challenge_id,
            "submission_id": command.submission_id,
            "challenger_ref": command.challenger_ref,
            "finding_kind": command.finding_kind,
            "evidence_refs": command.evidence_refs,
            "deposit_atoms": command.deposit.atoms,
            "now_epoch_s": command.now_epoch_s,
        }
    elif isinstance(command, ResolveChallenge):
        value = {
            "kind": "resolve_challenge",
            "command_id": command.command_id,
            "challenge_id": command.challenge_id,
            "verifier_ref": command.verifier_ref,
            "verifier_receipt_ref": command.verifier_receipt_ref,
            "upheld": command.upheld,
            "now_epoch_s": command.now_epoch_s,
        }
    elif isinstance(command, AdvanceBounty):
        value = {
            "kind": "advance_bounty",
            "command_id": command.command_id,
            "now_epoch_s": command.now_epoch_s,
        }
    elif isinstance(command, SettleBounty):
        value = {
            "kind": "settle_bounty",
            "command_id": command.command_id,
            "settlement_ref": command.settlement_ref,
            "payouts": tuple(
                {
                    "recipient_ref": payout.recipient_ref,
                    "submission_id": payout.submission_id,
                    "amount_atoms": payout.amount.atoms,
                }
                for payout in command.payouts
            ),
            "now_epoch_s": command.now_epoch_s,
        }
    else:
        assert isinstance(command, CancelBounty)
        value = {
            "kind": "cancel_bounty",
            "command_id": command.command_id,
            "sponsor_ref": command.sponsor_ref,
            "now_epoch_s": command.now_epoch_s,
        }
    frozen = freeze_json(value)
    assert isinstance(frozen, FrozenDict)
    return frozen


def _state_json(state: BountyState) -> FrozenDict[JsonValue]:
    value = {
        "terms": {
            "bounty_id": state.terms.bounty_id,
            "sponsor_ref": state.terms.sponsor_ref,
            "claim_ref": state.terms.claim_ref,
            "context_ref": state.terms.context_ref,
            "reward_atoms": state.terms.reward.atoms,
            "minimum_submission_bond_atoms": state.terms.minimum_submission_bond.atoms,
            "deadline_epoch_s": state.terms.deadline_epoch_s,
            "challenge_window_seconds": state.terms.challenge_window_seconds,
            "accepted_recipe_refs": tuple(sorted(state.terms.accepted_recipe_refs)),
            "accepted_verifier_refs": tuple(sorted(state.terms.accepted_verifier_refs)),
        },
        "phase": state.phase.value,
        "escrow_locked_atoms": state.escrow_locked.atoms,
        "submissions": tuple(
            {
                "submission_id": submission.submission_id,
                "submitter_ref": submission.submitter_ref,
                "recipe_ref": submission.recipe_ref,
                "verifier_ref": submission.verifier_ref,
                "evidence_refs": submission.evidence_refs,
                "artifact_refs": submission.artifact_refs,
                "submitted_at": submission.submitted_at,
                "status": submission.status.value,
                "bond_locked_atoms": submission.bond_locked.atoms,
                "verifier_receipt_ref": submission.verifier_receipt_ref,
            }
            for submission in state.submissions
        ),
        "challenges": tuple(
            {
                "challenge_id": challenge.challenge_id,
                "submission_id": challenge.submission_id,
                "challenger_ref": challenge.challenger_ref,
                "finding_kind": challenge.finding_kind,
                "evidence_refs": challenge.evidence_refs,
                "opened_at": challenge.opened_at,
                "status": challenge.status.value,
                "deposit_locked_atoms": challenge.deposit_locked.atoms,
                "verifier_receipt_ref": challenge.verifier_receipt_ref,
            }
            for challenge in state.challenges
        ),
        "payable_submission_ids": state.payable_submission_ids,
        "settlement_ref": state.settlement_ref,
        "processed_command_ids": tuple(sorted(state.processed_command_ids)),
    }
    frozen = freeze_json(value)
    assert isinstance(frozen, FrozenDict)
    return frozen


def _effect(
    kind: str,
    account_ref: str,
    amount: Amount,
    subject_ref: str,
    **metadata: JsonValue,
) -> MarketEffect:
    frozen = freeze_json(metadata)
    assert isinstance(frozen, FrozenDict)
    return MarketEffect(
        kind=kind,
        account_ref=account_ref,
        amount=amount,
        subject_ref=subject_ref,
        metadata=frozen,
    )


def _submission(state: BountyState, submission_id: str) -> SubmissionState | None:
    return next((value for value in state.submissions if value.submission_id == submission_id), None)


def _challenge(state: BountyState, challenge_id: str) -> ChallengeState | None:
    return next((value for value in state.challenges if value.challenge_id == challenge_id), None)


def _replace_submission(
    submissions: tuple[SubmissionState, ...],
    replacement: SubmissionState,
) -> tuple[SubmissionState, ...]:
    return tuple(replacement if value.submission_id == replacement.submission_id else value for value in submissions)


def _replace_challenge(
    challenges: tuple[ChallengeState, ...],
    replacement: ChallengeState,
) -> tuple[ChallengeState, ...]:
    return tuple(replacement if value.challenge_id == replacement.challenge_id else value for value in challenges)


def _challenge_deadline(state: BountyState) -> int:
    return state.terms.deadline_epoch_s + state.terms.challenge_window_seconds


def _resolution_deadline(
    state: BountyState,
    challenge: ChallengeState,
    policy: MarketPolicy,
) -> int:
    return max(
        _challenge_deadline(state),
        challenge.opened_at + policy.challenge_resolution_seconds,
    )


def _valid_ref(value: object) -> bool:
    return isinstance(value, str) and bool(_REF_RE.fullmatch(value))


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and bool(_ID_RE.fullmatch(value))


def _reject(code: str, field: str, reason: str) -> Reject:
    details = freeze_json({"field": field, "reason": reason})
    assert isinstance(details, FrozenDict)
    return Reject(code=code, details=details)
