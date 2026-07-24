from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import TypeAlias

from .codec import canonical_hash
from .result import Accept, CommittedFailure, Reject
from .values import Amount, FrozenDict, JsonValue, freeze_json


_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")


class BountyPhase(str, Enum):
    DRAFT = "draft"
    OPEN = "open"
    PAYABLE = "payable"
    SETTLED = "settled"
    EXPIRED = "expired"
    CANCELED = "canceled"


class SubmissionStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ChallengeStatus(str, Enum):
    OPEN = "open"
    UPHELD = "upheld"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class BountyTerms:
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
        object.__setattr__(self, "accepted_recipe_refs", frozenset(self.accepted_recipe_refs))
        object.__setattr__(self, "accepted_verifier_refs", frozenset(self.accepted_verifier_refs))
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


@dataclass(frozen=True, slots=True)
class SubmissionState:
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))
        if not _valid_id(self.submission_id):
            raise ValueError("invalid submission_id")
        if not self.submitter_ref:
            raise ValueError("submitter_ref must be non-empty")
        if not (_valid_ref(self.recipe_ref) and _valid_ref(self.verifier_ref)):
            raise ValueError("recipe_ref and verifier_ref must be sha256 refs")
        if not self.evidence_refs or not all(_valid_ref(ref) for ref in self.evidence_refs):
            raise ValueError("evidence_refs must be non-empty sha256 refs")
        if not all(_valid_ref(ref) for ref in self.artifact_refs):
            raise ValueError("artifact_refs must be sha256 refs")
        if not isinstance(self.submitted_at, int) or isinstance(self.submitted_at, bool) or self.submitted_at < 0:
            raise ValueError("submitted_at must be a non-negative integer")
        if not isinstance(self.status, SubmissionStatus):
            raise TypeError("status must be SubmissionStatus")
        if not isinstance(self.bond_locked, Amount):
            raise TypeError("bond_locked must be Amount")
        if self.status is SubmissionStatus.PENDING:
            if self.verifier_receipt_ref is not None:
                raise ValueError("pending submission cannot carry verifier receipt")
        else:
            if self.verifier_receipt_ref is None or not _valid_ref(self.verifier_receipt_ref):
                raise ValueError("resolved submission requires verifier receipt ref")
        if self.status is SubmissionStatus.REJECTED and self.bond_locked.atoms != 0:
            raise ValueError("rejected submission cannot retain a locked bond")


@dataclass(frozen=True, slots=True)
class ChallengeState:
    challenge_id: str
    submission_id: str
    challenger_ref: str
    finding_kind: str
    evidence_refs: tuple[str, ...]
    opened_at: int
    status: ChallengeStatus
    deposit_locked: Amount
    verifier_receipt_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        if not (_valid_id(self.challenge_id) and _valid_id(self.submission_id)):
            raise ValueError("invalid challenge_id or submission_id")
        if not self.challenger_ref or not self.finding_kind:
            raise ValueError("challenger_ref and finding_kind must be non-empty")
        if not self.evidence_refs or not all(_valid_ref(ref) for ref in self.evidence_refs):
            raise ValueError("challenge evidence_refs must be non-empty sha256 refs")
        if not isinstance(self.opened_at, int) or isinstance(self.opened_at, bool) or self.opened_at < 0:
            raise ValueError("opened_at must be a non-negative integer")
        if not isinstance(self.status, ChallengeStatus):
            raise TypeError("status must be ChallengeStatus")
        if not isinstance(self.deposit_locked, Amount):
            raise TypeError("deposit_locked must be Amount")
        if self.status is ChallengeStatus.OPEN:
            if self.deposit_locked.atoms <= 0:
                raise ValueError("open challenge requires a positive locked deposit")
            if self.verifier_receipt_ref is not None:
                raise ValueError("open challenge cannot carry verifier receipt")
        else:
            if self.deposit_locked.atoms != 0:
                raise ValueError("resolved challenge cannot retain a locked deposit")
            if self.verifier_receipt_ref is None or not _valid_ref(self.verifier_receipt_ref):
                raise ValueError("resolved challenge requires verifier receipt ref")


@dataclass(frozen=True, slots=True)
class BountyState:
    terms: BountyTerms
    phase: BountyPhase = BountyPhase.DRAFT
    escrow_locked: Amount = Amount(0)
    submissions: tuple[SubmissionState, ...] = ()
    challenges: tuple[ChallengeState, ...] = ()
    payable_submission_ids: tuple[str, ...] = ()
    settlement_ref: str | None = None
    processed_command_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        object.__setattr__(self, "submissions", tuple(self.submissions))
        object.__setattr__(self, "challenges", tuple(self.challenges))
        object.__setattr__(self, "payable_submission_ids", tuple(self.payable_submission_ids))
        object.__setattr__(self, "processed_command_ids", frozenset(self.processed_command_ids))
        violations = bounty_state_violations(self)
        if violations:
            raise ValueError(f"invalid bounty state: {violations[0]}")


@dataclass(frozen=True, slots=True)
class MarketPolicy:
    minimum_bounty: Amount
    minimum_submission_bond: Amount
    minimum_challenge_deposit: Amount
    slashable_findings: frozenset[str]
    treasury_ref: str = "protocol:treasury"

    def __post_init__(self) -> None:
        object.__setattr__(self, "slashable_findings", frozenset(self.slashable_findings))
        if not self.slashable_findings:
            raise ValueError("slashable_findings must be non-empty")
        if not self.treasury_ref:
            raise ValueError("treasury_ref must be non-empty")


@dataclass(frozen=True, slots=True)
class MarketEffect:
    kind: str
    account_ref: str
    amount: Amount
    subject_ref: str
    metadata: FrozenDict[JsonValue] = FrozenDict()

    def __post_init__(self) -> None:
        frozen = freeze_json(self.metadata)
        if not isinstance(frozen, FrozenDict):
            raise TypeError("market effect metadata must be an object")
        object.__setattr__(self, "metadata", frozen)
        if not self.kind or not self.account_ref or not self.subject_ref:
            raise ValueError("market effect kind, account_ref, and subject_ref must be non-empty")
        if not isinstance(self.amount, Amount):
            raise TypeError("market effect amount must be Amount")

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
class TransitionReceipt:
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
class OpenBounty:
    command_id: str
    sponsor_ref: str
    funded: Amount
    now_epoch_s: int


@dataclass(frozen=True, slots=True)
class SubmitCandidate:
    command_id: str
    submission_id: str
    submitter_ref: str
    recipe_ref: str
    verifier_ref: str
    evidence_refs: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    bond: Amount
    now_epoch_s: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))


@dataclass(frozen=True, slots=True)
class VerifySubmission:
    command_id: str
    submission_id: str
    verifier_ref: str
    verifier_receipt_ref: str
    accepted: bool
    now_epoch_s: int


@dataclass(frozen=True, slots=True)
class OpenChallenge:
    command_id: str
    challenge_id: str
    submission_id: str
    challenger_ref: str
    finding_kind: str
    evidence_refs: tuple[str, ...]
    deposit: Amount
    now_epoch_s: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))


@dataclass(frozen=True, slots=True)
class ResolveChallenge:
    command_id: str
    challenge_id: str
    verifier_ref: str
    verifier_receipt_ref: str
    upheld: bool
    now_epoch_s: int


@dataclass(frozen=True, slots=True)
class AdvanceBounty:
    command_id: str
    now_epoch_s: int


@dataclass(frozen=True, slots=True)
class Payout:
    recipient_ref: str
    submission_id: str
    amount: Amount

    def __post_init__(self) -> None:
        if not self.recipient_ref or not _valid_id(self.submission_id):
            raise ValueError("invalid payout recipient or submission_id")
        if not isinstance(self.amount, Amount) or self.amount.atoms <= 0:
            raise ValueError("payout amount must be positive")


@dataclass(frozen=True, slots=True)
class SettleBounty:
    command_id: str
    settlement_ref: str
    payouts: tuple[Payout, ...]
    now_epoch_s: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "payouts", tuple(self.payouts))


@dataclass(frozen=True, slots=True)
class CancelBounty:
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



def bounty_state_violations(state: BountyState) -> tuple[str, ...]:
    """Return stable structural invariant violations for one immutable state.

    This is intentionally independent of command policy. It captures only
    facts that must hold for every representable market state, so transition
    constructors and mounted formal adapters share one boundary contract.
    """

    violations: list[str] = []
    if not isinstance(state.terms, BountyTerms):
        violations.append("terms_type")
    if not isinstance(state.phase, BountyPhase):
        violations.append("phase_type")
    if not isinstance(state.escrow_locked, Amount):
        violations.append("escrow_type")
    if not all(isinstance(value, SubmissionState) for value in state.submissions):
        violations.append("submission_type")
        return tuple(sorted(set(violations)))
    if not all(isinstance(value, ChallengeState) for value in state.challenges):
        violations.append("challenge_type")
        return tuple(sorted(set(violations)))

    submission_ids = tuple(submission.submission_id for submission in state.submissions)
    if len(set(submission_ids)) != len(submission_ids):
        violations.append("duplicate_submission_id")
    challenge_ids = tuple(challenge.challenge_id for challenge in state.challenges)
    if len(set(challenge_ids)) != len(challenge_ids):
        violations.append("duplicate_challenge_id")
    known_submissions = set(submission_ids)
    if any(challenge.submission_id not in known_submissions for challenge in state.challenges):
        violations.append("challenge_unknown_submission")
    open_challenge_subjects = tuple(
        challenge.submission_id
        for challenge in state.challenges
        if challenge.status is ChallengeStatus.OPEN
    )
    if len(set(open_challenge_subjects)) != len(open_challenge_subjects):
        violations.append("multiple_open_challenges_per_submission")

    payable_ids = tuple(state.payable_submission_ids)
    if len(set(payable_ids)) != len(payable_ids):
        violations.append("duplicate_payable_submission_id")
    submissions_by_id = {submission.submission_id: submission for submission in state.submissions}
    if any(submission_id not in submissions_by_id for submission_id in payable_ids):
        violations.append("payable_unknown_submission")
    if any(
        submissions_by_id[submission_id].status is not SubmissionStatus.VERIFIED
        for submission_id in payable_ids
        if submission_id in submissions_by_id
    ):
        violations.append("payable_submission_not_verified")

    open_challenge = any(challenge.status is ChallengeStatus.OPEN for challenge in state.challenges)
    if open_challenge and state.phase is not BountyPhase.OPEN:
        violations.append("open_challenge_outside_open_phase")
    if any(
        challenge.status is ChallengeStatus.OPEN and challenge.deposit_locked.atoms <= 0
        for challenge in state.challenges
    ):
        violations.append("open_challenge_without_deposit")
    if any(
        challenge.status is not ChallengeStatus.OPEN and challenge.deposit_locked.atoms != 0
        for challenge in state.challenges
    ):
        violations.append("resolved_challenge_retains_deposit")
    if any(
        submission.status is SubmissionStatus.REJECTED and submission.bond_locked.atoms != 0
        for submission in state.submissions
    ):
        violations.append("rejected_submission_retains_bond")

    if state.phase is BountyPhase.DRAFT:
        if state.escrow_locked.atoms != 0:
            violations.append("draft_has_escrow")
        if state.submissions or state.challenges or state.payable_submission_ids or state.settlement_ref is not None:
            violations.append("draft_has_activity")
        if state.processed_command_ids:
            violations.append("draft_has_processed_command")
    elif state.phase is BountyPhase.OPEN:
        if state.escrow_locked.atoms <= 0:
            violations.append("open_without_escrow")
        if state.payable_submission_ids:
            violations.append("open_has_payable_ids")
        if state.settlement_ref is not None:
            violations.append("open_has_settlement")
    elif state.phase is BountyPhase.PAYABLE:
        if state.escrow_locked.atoms <= 0:
            violations.append("payable_without_escrow")
        if not state.payable_submission_ids:
            violations.append("payable_without_submission")
        if open_challenge:
            violations.append("payable_with_open_challenge")
        if state.settlement_ref is not None:
            violations.append("payable_has_settlement")
    elif state.phase is BountyPhase.SETTLED:
        if state.escrow_locked.atoms != 0:
            violations.append("settled_retains_escrow")
        if not state.payable_submission_ids:
            violations.append("settled_without_payable_submission")
        if not state.settlement_ref:
            violations.append("settled_without_receipt")
    elif state.phase is BountyPhase.EXPIRED:
        if state.escrow_locked.atoms != 0:
            violations.append("expired_retains_escrow")
        if state.payable_submission_ids:
            violations.append("expired_has_payable_ids")
        if state.settlement_ref is not None:
            violations.append("expired_has_settlement")
    elif state.phase is BountyPhase.CANCELED:
        if state.escrow_locked.atoms != 0:
            violations.append("canceled_retains_escrow")
        if state.submissions or state.challenges or state.payable_submission_ids:
            violations.append("canceled_has_activity")
        if state.settlement_ref is not None:
            violations.append("canceled_has_settlement")

    if state.phase in {BountyPhase.SETTLED, BountyPhase.EXPIRED, BountyPhase.CANCELED}:
        if any(submission.bond_locked.atoms != 0 for submission in state.submissions):
            violations.append("terminal_retains_submission_bond")
        if any(challenge.deposit_locked.atoms != 0 for challenge in state.challenges):
            violations.append("terminal_retains_challenge_deposit")
        if open_challenge:
            violations.append("terminal_has_open_challenge")
    if state.phase is not BountyPhase.SETTLED and state.settlement_ref is not None:
        violations.append("nonsettled_has_settlement")
    if any(not _valid_id(command_id) for command_id in state.processed_command_ids):
        violations.append("invalid_processed_command_id")
    return tuple(sorted(set(violations)))


def initial_bounty(terms: BountyTerms) -> BountyState:
    return BountyState(terms=terms)


def apply_market_command(
    state: BountyState,
    command: MarketCommand,
    policy: MarketPolicy,
) -> MarketDecision:
    """Apply one total deterministic market transition over immutable values."""

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
        return _advance_bounty(state, command)
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
    # The challenge window governs admission of new challenges. Once admitted,
    # a challenge remains resolvable after the window closes; otherwise both
    # resolution and advancement become permanently disabled.
    challenge = _challenge(state, command.challenge_id)
    if challenge is None:
        return _reject("UNKNOWN_ENTITY", "challenge_id", command.challenge_id)
    if challenge.status is not ChallengeStatus.OPEN:
        return _reject("POLICY_MISMATCH", "challenge_status", challenge.status.value)
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


def _advance_bounty(state: BountyState, command: AdvanceBounty) -> MarketDecision:
    if state.phase is not BountyPhase.OPEN:
        return _reject("WRONG_PHASE", "phase", state.phase.value)
    if command.now_epoch_s <= _challenge_deadline(state):
        return _reject("TIME_WINDOW", "challenge_deadline", "window is still open")
    if any(challenge.status is ChallengeStatus.OPEN for challenge in state.challenges):
        return _reject("POLICY_MISMATCH", "challenges", "open challenge remains")

    eligible = tuple(
        submission.submission_id
        for submission in sorted(state.submissions, key=lambda value: (value.submitted_at, value.submission_id))
        if submission.status is SubmissionStatus.VERIFIED
    )
    if eligible:
        next_state = replace(
            state,
            phase=BountyPhase.PAYABLE,
            payable_submission_ids=eligible,
            processed_command_ids=state.processed_command_ids | frozenset({command.command_id}),
        )
        return _accept(state, next_state, command, "bounty_payable", ())

    effects: list[MarketEffect] = [
        _effect(
            "refund_escrow",
            state.terms.sponsor_ref,
            state.escrow_locked,
            state.terms.bounty_id,
            reason="no_payable_submission",
        )
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
        return _reject("INVALID_COMMAND", "command_id", command.command_id)
    if command.now_epoch_s < 0:
        return _reject("INVALID_COMMAND", "now_epoch_s", str(command.now_epoch_s))
    return None


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


def _valid_ref(value: str) -> bool:
    return bool(_REF_RE.fullmatch(value))


def _valid_id(value: str) -> bool:
    return bool(_ID_RE.fullmatch(value))


def _reject(code: str, field: str, reason: str) -> Reject:
    details = freeze_json({"field": field, "reason": reason})
    assert isinstance(details, FrozenDict)
    return Reject(code=code, details=details)
