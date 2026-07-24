"""One canonical market state invariant projection.

This module provides the single public pure function
``market_state_violations(value) -> tuple[MarketStateViolation, ...]``
used by both ``apply_market_command`` (runtime validation) and formal
adapters (ESSO, audit tools). There is no second independent definition
of valid ``BountyState``.

Command-specific policy stays in ``apply_market_command``. This projection
only describes properties that every representable state must satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from .codec import canonical_hash
from .market import (
    BountyPhase,
    BountyState,
    BountyTerms,
    ChallengeState,
    ChallengeStatus,
    SubmissionState,
    SubmissionStatus,
)
from .values import (
    Amount,
    ClosedStrEnum,
    DeeplyImmutable,
    FrozenDict,
    JsonValue,
    freeze_json,
)


class MarketStateViolationCode(ClosedStrEnum):
    __slots__ = ()

    STATE_TYPE: ClassVar[MarketStateViolationCode]
    TERMS_TYPE: ClassVar[MarketStateViolationCode]
    PHASE_TYPE: ClassVar[MarketStateViolationCode]
    ESCROW_TYPE: ClassVar[MarketStateViolationCode]
    SUBMISSION_TYPE: ClassVar[MarketStateViolationCode]
    CHALLENGE_TYPE: ClassVar[MarketStateViolationCode]
    DUPLICATE_SUBMISSION_ID: ClassVar[MarketStateViolationCode]
    DUPLICATE_CHALLENGE_ID: ClassVar[MarketStateViolationCode]
    CHALLENGE_UNKNOWN_SUBMISSION: ClassVar[MarketStateViolationCode]
    DUPLICATE_PAYABLE_SUBMISSION_ID: ClassVar[MarketStateViolationCode]
    PAYABLE_UNKNOWN_SUBMISSION: ClassVar[MarketStateViolationCode]
    PAYABLE_SUBMISSION_NOT_VERIFIED: ClassVar[MarketStateViolationCode]
    MULTIPLE_OPEN_CHALLENGES: ClassVar[MarketStateViolationCode]
    OPEN_CHALLENGE_OUTSIDE_OPEN_PHASE: ClassVar[MarketStateViolationCode]
    OPEN_CHALLENGE_WITHOUT_DEPOSIT: ClassVar[MarketStateViolationCode]
    RESOLVED_CHALLENGE_RETAINS_DEPOSIT: ClassVar[MarketStateViolationCode]
    REJECTED_SUBMISSION_RETAINS_BOND: ClassVar[MarketStateViolationCode]
    TERMINAL_RETAINS_ESCROW: ClassVar[MarketStateViolationCode]
    TERMINAL_RETAINS_BOND: ClassVar[MarketStateViolationCode]
    TERMINAL_RETAINS_DEPOSIT: ClassVar[MarketStateViolationCode]
    TERMINAL_HAS_OPEN_CHALLENGE: ClassVar[MarketStateViolationCode]
    NON_SETTLED_HAS_SETTLEMENT: ClassVar[MarketStateViolationCode]
    SETTLEMENT_REF_TYPE: ClassVar[MarketStateViolationCode]
    PROCESSED_COMMAND_IDS_TYPE: ClassVar[MarketStateViolationCode]
    DRAFT_HAS_ESCROW: ClassVar[MarketStateViolationCode]
    DRAFT_HAS_ACTIVITY: ClassVar[MarketStateViolationCode]
    OPEN_WITHOUT_ESCROW: ClassVar[MarketStateViolationCode]
    OPEN_HAS_PAYABLE_IDS: ClassVar[MarketStateViolationCode]
    OPEN_HAS_SETTLEMENT: ClassVar[MarketStateViolationCode]
    PAYABLE_WITHOUT_ESCROW: ClassVar[MarketStateViolationCode]
    PAYABLE_WITHOUT_SUBMISSION: ClassVar[MarketStateViolationCode]
    PAYABLE_WITH_OPEN_CHALLENGE: ClassVar[MarketStateViolationCode]
    SETTLED_RETAINS_ESCROW: ClassVar[MarketStateViolationCode]
    SETTLED_WITHOUT_PAYABLE_SUBMISSION: ClassVar[MarketStateViolationCode]
    SETTLED_WITHOUT_RECEIPT: ClassVar[MarketStateViolationCode]
    EXPIRED_RETAINS_ESCROW: ClassVar[MarketStateViolationCode]
    EXPIRED_HAS_PAYABLE_IDS: ClassVar[MarketStateViolationCode]
    CANCELED_RETAINS_ESCROW: ClassVar[MarketStateViolationCode]
    CANCELED_HAS_ACTIVITY: ClassVar[MarketStateViolationCode]
    _symbols = (
        ("STATE_TYPE", "state_type"),
        ("TERMS_TYPE", "terms_type"),
        ("PHASE_TYPE", "phase_type"),
        ("ESCROW_TYPE", "escrow_type"),
        ("SUBMISSION_TYPE", "submission_type"),
        ("CHALLENGE_TYPE", "challenge_type"),
        ("DUPLICATE_SUBMISSION_ID", "duplicate_submission_id"),
        ("DUPLICATE_CHALLENGE_ID", "duplicate_challenge_id"),
        ("CHALLENGE_UNKNOWN_SUBMISSION", "challenge_unknown_submission"),
        ("DUPLICATE_PAYABLE_SUBMISSION_ID", "duplicate_payable_submission_id"),
        ("PAYABLE_UNKNOWN_SUBMISSION", "payable_unknown_submission"),
        ("PAYABLE_SUBMISSION_NOT_VERIFIED", "payable_submission_not_verified"),
        ("MULTIPLE_OPEN_CHALLENGES", "multiple_open_challenges"),
        ("OPEN_CHALLENGE_OUTSIDE_OPEN_PHASE", "open_challenge_outside_open_phase"),
        ("OPEN_CHALLENGE_WITHOUT_DEPOSIT", "open_challenge_without_deposit"),
        ("RESOLVED_CHALLENGE_RETAINS_DEPOSIT", "resolved_challenge_retains_deposit"),
        ("REJECTED_SUBMISSION_RETAINS_BOND", "rejected_submission_retains_bond"),
        ("TERMINAL_RETAINS_ESCROW", "terminal_retains_escrow"),
        ("TERMINAL_RETAINS_BOND", "terminal_retains_bond"),
        ("TERMINAL_RETAINS_DEPOSIT", "terminal_retains_deposit"),
        ("TERMINAL_HAS_OPEN_CHALLENGE", "terminal_has_open_challenge"),
        ("NON_SETTLED_HAS_SETTLEMENT", "non_settled_has_settlement"),
        ("SETTLEMENT_REF_TYPE", "settlement_ref_type"),
        ("PROCESSED_COMMAND_IDS_TYPE", "processed_command_ids_type"),
        ("DRAFT_HAS_ESCROW", "draft_has_escrow"),
        ("DRAFT_HAS_ACTIVITY", "draft_has_activity"),
        ("OPEN_WITHOUT_ESCROW", "open_without_escrow"),
        ("OPEN_HAS_PAYABLE_IDS", "open_has_payable_ids"),
        ("OPEN_HAS_SETTLEMENT", "open_has_settlement"),
        ("PAYABLE_WITHOUT_ESCROW", "payable_without_escrow"),
        ("PAYABLE_WITHOUT_SUBMISSION", "payable_without_submission"),
        ("PAYABLE_WITH_OPEN_CHALLENGE", "payable_with_open_challenge"),
        ("SETTLED_RETAINS_ESCROW", "settled_retains_escrow"),
        ("SETTLED_WITHOUT_PAYABLE_SUBMISSION", "settled_without_payable_submission"),
        ("SETTLED_WITHOUT_RECEIPT", "settled_without_receipt"),
        ("EXPIRED_RETAINS_ESCROW", "expired_retains_escrow"),
        ("EXPIRED_HAS_PAYABLE_IDS", "expired_has_payable_ids"),
        ("CANCELED_RETAINS_ESCROW", "canceled_retains_escrow"),
        ("CANCELED_HAS_ACTIVITY", "canceled_has_activity"),
    )


@dataclass(frozen=True, slots=True)
class MarketStateViolation(DeeplyImmutable):
    """A single structural invariant violation as a typed immutable value."""

    code: MarketStateViolationCode
    field_path: str
    detail: str

    def __post_init__(self) -> None:
        if type(self.code) is not MarketStateViolationCode:
            raise TypeError("MarketStateViolation.code must be a MarketStateViolationCode")
        if type(self.field_path) is not str or not self.field_path:
            raise ValueError("field_path must be a non-empty string")
        if type(self.detail) is not str:
            raise TypeError("detail must be a string")
        DeeplyImmutable.__post_init__(self)

    def render(self) -> str:
        return f"{self.code.value} at {self.field_path}: {self.detail}"

    def as_json(self) -> FrozenDict[JsonValue]:
        value = freeze_json(
            {
                "code": self.code.value,
                "field_path": self.field_path,
                "detail": self.detail,
            }
        )
        assert isinstance(value, FrozenDict)
        return value


def market_state_violations(value: object) -> tuple[MarketStateViolation, ...]:
    """Project structural market invariants as stable pure values.

    Returns a tuple of typed ``MarketStateViolation`` values. An empty tuple
    means the state satisfies all structural invariants. This is the one
    canonical projection used by both runtime validation and formal adapters.
    """

    if type(value) is not BountyState:
        return (
            MarketStateViolation(
                code=MarketStateViolationCode.STATE_TYPE,
                field_path="$",
                detail=f"expected BountyState, got {type(value).__name__}",
            ),
        )
    state: BountyState = value
    violations: list[MarketStateViolation] = []
    _check_types(state, violations)
    if violations:
        return tuple(violations)
    _check_uniqueness(state, violations)
    _check_references(state, violations)
    _check_payable(state, violations)
    _check_challenge_invariants(state, violations)
    _check_phase_invariants(state, violations)
    _check_terminal_invariants(state, violations)
    return tuple(violations)


def _violation(
    code: MarketStateViolationCode,
    field_path: str,
    detail: str,
) -> MarketStateViolation:
    return MarketStateViolation(code=code, field_path=field_path, detail=detail)


def _check_types(state: BountyState, out: list[MarketStateViolation]) -> None:
    if type(state.terms) is not BountyTerms:
        out.append(_violation(MarketStateViolationCode.TERMS_TYPE, "$.terms", "must be BountyTerms"))
    if type(state.phase) is not BountyPhase:
        out.append(_violation(MarketStateViolationCode.PHASE_TYPE, "$.phase", "must be BountyPhase"))
    if type(state.escrow_locked) is not Amount:
        out.append(_violation(MarketStateViolationCode.ESCROW_TYPE, "$.escrow_locked", "must be Amount"))
    if not isinstance(state.submissions, tuple) or any(
        type(value) is not SubmissionState for value in state.submissions
    ):
        out.append(_violation(MarketStateViolationCode.SUBMISSION_TYPE, "$.submissions", "must be tuple of SubmissionState"))
        return
    if not isinstance(state.challenges, tuple) or any(
        type(value) is not ChallengeState for value in state.challenges
    ):
        out.append(_violation(MarketStateViolationCode.CHALLENGE_TYPE, "$.challenges", "must be tuple of ChallengeState"))
    if state.settlement_ref is not None and (not isinstance(state.settlement_ref, str) or not state.settlement_ref):
        out.append(_violation(MarketStateViolationCode.SETTLEMENT_REF_TYPE, "$.settlement_ref", "must be null or non-empty string"))
    if not isinstance(state.processed_command_ids, frozenset) or not all(
        isinstance(cid, str) and bool(cid) for cid in state.processed_command_ids
    ):
        out.append(_violation(MarketStateViolationCode.PROCESSED_COMMAND_IDS_TYPE, "$.processed_command_ids", "must be frozenset of non-empty strings"))


def _check_uniqueness(state: BountyState, out: list[MarketStateViolation]) -> None:
    submission_ids = [value.submission_id for value in state.submissions]
    if len(set(submission_ids)) != len(submission_ids):
        out.append(_violation(MarketStateViolationCode.DUPLICATE_SUBMISSION_ID, "$.submissions", "ids must be unique"))
    challenge_ids = [value.challenge_id for value in state.challenges]
    if len(set(challenge_ids)) != len(challenge_ids):
        out.append(_violation(MarketStateViolationCode.DUPLICATE_CHALLENGE_ID, "$.challenges", "ids must be unique"))


def _check_references(state: BountyState, out: list[MarketStateViolation]) -> None:
    submissions_by_id = {value.submission_id: value for value in state.submissions}
    for challenge in state.challenges:
        if challenge.submission_id not in submissions_by_id:
            out.append(_violation(
                MarketStateViolationCode.CHALLENGE_UNKNOWN_SUBMISSION,
                f"$.challenges[{challenge.challenge_id}]",
                f"references unknown submission {challenge.submission_id}",
            ))


def _check_payable(state: BountyState, out: list[MarketStateViolation]) -> None:
    payable_ids = list(state.payable_submission_ids)
    if len(set(payable_ids)) != len(payable_ids):
        out.append(_violation(MarketStateViolationCode.DUPLICATE_PAYABLE_SUBMISSION_ID, "$.payable_submission_ids", "must be unique"))
    submissions_by_id = {value.submission_id: value for value in state.submissions}
    for submission_id in payable_ids:
        submission = submissions_by_id.get(submission_id)
        if submission is None:
            out.append(_violation(
                MarketStateViolationCode.PAYABLE_UNKNOWN_SUBMISSION,
                f"$.payable_submission_ids[{submission_id}]",
                "references unknown submission",
            ))
        elif submission.status is not SubmissionStatus.VERIFIED:
            out.append(_violation(
                MarketStateViolationCode.PAYABLE_SUBMISSION_NOT_VERIFIED,
                f"$.payable_submission_ids[{submission_id}]",
                f"submission status is {submission.status.value}, not verified",
            ))


def _check_challenge_invariants(state: BountyState, out: list[MarketStateViolation]) -> None:
    open_challenges = [value for value in state.challenges if value.status is ChallengeStatus.OPEN]
    open_subjects = [value.submission_id for value in open_challenges]
    if len(set(open_subjects)) != len(open_subjects):
        out.append(_violation(MarketStateViolationCode.MULTIPLE_OPEN_CHALLENGES, "$.challenges", "multiple open challenges per submission"))
    if open_challenges and state.phase is not BountyPhase.OPEN:
        out.append(_violation(MarketStateViolationCode.OPEN_CHALLENGE_OUTSIDE_OPEN_PHASE, "$.phase", "open challenges exist outside OPEN phase"))
    for challenge in open_challenges:
        if challenge.deposit_locked.atoms <= 0:
            out.append(_violation(
                MarketStateViolationCode.OPEN_CHALLENGE_WITHOUT_DEPOSIT,
                f"$.challenges[{challenge.challenge_id}]",
                "open challenge has no locked deposit",
            ))
    for challenge in state.challenges:
        if challenge.status is not ChallengeStatus.OPEN and challenge.deposit_locked.atoms != 0:
            out.append(_violation(
                MarketStateViolationCode.RESOLVED_CHALLENGE_RETAINS_DEPOSIT,
                f"$.challenges[{challenge.challenge_id}]",
                "resolved challenge retains deposit",
            ))
    for submission in state.submissions:
        if submission.status is SubmissionStatus.REJECTED and submission.bond_locked.atoms != 0:
            out.append(_violation(
                MarketStateViolationCode.REJECTED_SUBMISSION_RETAINS_BOND,
                f"$.submissions[{submission.submission_id}]",
                "rejected submission retains bond",
            ))


def _check_phase_invariants(state: BountyState, out: list[MarketStateViolation]) -> None:
    phase = state.phase
    payable_ids = state.payable_submission_ids
    if phase is BountyPhase.DRAFT:
        if state.escrow_locked.atoms != 0:
            out.append(_violation(MarketStateViolationCode.DRAFT_HAS_ESCROW, "$.escrow_locked", "draft must have zero escrow"))
        if state.submissions or state.challenges or payable_ids or state.settlement_ref is not None:
            out.append(_violation(MarketStateViolationCode.DRAFT_HAS_ACTIVITY, "$", "draft must have no activity"))
    elif phase is BountyPhase.OPEN:
        if state.escrow_locked.atoms <= 0:
            out.append(_violation(MarketStateViolationCode.OPEN_WITHOUT_ESCROW, "$.escrow_locked", "open must have positive escrow"))
        if payable_ids:
            out.append(_violation(MarketStateViolationCode.OPEN_HAS_PAYABLE_IDS, "$.payable_submission_ids", "open must have no payable ids"))
        if state.settlement_ref is not None:
            out.append(_violation(MarketStateViolationCode.OPEN_HAS_SETTLEMENT, "$.settlement_ref", "open must have no settlement"))
    elif phase is BountyPhase.PAYABLE:
        if state.escrow_locked.atoms <= 0:
            out.append(_violation(MarketStateViolationCode.PAYABLE_WITHOUT_ESCROW, "$.escrow_locked", "payable must have positive escrow"))
        if not payable_ids:
            out.append(_violation(MarketStateViolationCode.PAYABLE_WITHOUT_SUBMISSION, "$.payable_submission_ids", "payable must have at least one submission"))
        if any(value.status is ChallengeStatus.OPEN for value in state.challenges):
            out.append(_violation(MarketStateViolationCode.PAYABLE_WITH_OPEN_CHALLENGE, "$.challenges", "payable must have no open challenges"))
    elif phase is BountyPhase.SETTLED:
        if state.escrow_locked.atoms != 0:
            out.append(_violation(MarketStateViolationCode.SETTLED_RETAINS_ESCROW, "$.escrow_locked", "settled must have zero escrow"))
        if not payable_ids:
            out.append(_violation(MarketStateViolationCode.SETTLED_WITHOUT_PAYABLE_SUBMISSION, "$.payable_submission_ids", "settled must reference payable submissions"))
        if not state.settlement_ref:
            out.append(_violation(MarketStateViolationCode.SETTLED_WITHOUT_RECEIPT, "$.settlement_ref", "settled must have a settlement ref"))
    elif phase is BountyPhase.EXPIRED:
        if state.escrow_locked.atoms != 0:
            out.append(_violation(MarketStateViolationCode.EXPIRED_RETAINS_ESCROW, "$.escrow_locked", "expired must have zero escrow"))
        if payable_ids:
            out.append(_violation(MarketStateViolationCode.EXPIRED_HAS_PAYABLE_IDS, "$.payable_submission_ids", "expired must have no payable ids"))
    elif phase is BountyPhase.CANCELED:
        if state.escrow_locked.atoms != 0:
            out.append(_violation(MarketStateViolationCode.CANCELED_RETAINS_ESCROW, "$.escrow_locked", "canceled must have zero escrow"))
        if state.submissions or state.challenges or payable_ids:
            out.append(_violation(MarketStateViolationCode.CANCELED_HAS_ACTIVITY, "$", "canceled must have no activity"))


def _check_terminal_invariants(state: BountyState, out: list[MarketStateViolation]) -> None:
    terminal = state.phase in {BountyPhase.SETTLED, BountyPhase.EXPIRED, BountyPhase.CANCELED}
    if not terminal:
        if state.settlement_ref is not None:
            out.append(_violation(MarketStateViolationCode.NON_SETTLED_HAS_SETTLEMENT, "$.settlement_ref", "non-settled state has settlement ref"))
        return
    if any(value.bond_locked.atoms != 0 for value in state.submissions):
        out.append(_violation(MarketStateViolationCode.TERMINAL_RETAINS_BOND, "$.submissions", "terminal state retains submission bond"))
    if any(value.deposit_locked.atoms != 0 for value in state.challenges):
        out.append(_violation(MarketStateViolationCode.TERMINAL_RETAINS_DEPOSIT, "$.challenges", "terminal state retains challenge deposit"))
    if any(value.status is ChallengeStatus.OPEN for value in state.challenges):
        out.append(_violation(MarketStateViolationCode.TERMINAL_HAS_OPEN_CHALLENGE, "$.challenges", "terminal state has open challenge"))
