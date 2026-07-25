"""One canonical market state invariant projection.

This module provides the single public pure function
``market_state_violations(value) -> tuple[MarketStateViolation, ...]``
used by both ``apply_market_command`` (runtime validation) and formal
adapters (ESSO, audit tools). There is no second independent definition
of valid ``BountyState``.

All checks from the original ``_validate_market_state`` are expressed as
typed violations: terms fields, submission fields, challenge fields,
payable IDs, processed command IDs, settlement ref, uniqueness,
references, phase invariants, and terminal invariants.

Command-specific policy stays in ``apply_market_command``. This projection
only describes properties that every representable state must satisfy.
"""

from __future__ import annotations

import re
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


_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")


class MarketStateViolationCode(ClosedStrEnum):
    __slots__ = ()

    STATE_TYPE: ClassVar[MarketStateViolationCode]
    TERMS_TYPE: ClassVar[MarketStateViolationCode]
    TERMS_BOUNTY_ID: ClassVar[MarketStateViolationCode]
    TERMS_SPONSOR_REF: ClassVar[MarketStateViolationCode]
    TERMS_CLAIM_REF: ClassVar[MarketStateViolationCode]
    TERMS_CONTEXT_REF: ClassVar[MarketStateViolationCode]
    TERMS_REWARD: ClassVar[MarketStateViolationCode]
    TERMS_MIN_BOND: ClassVar[MarketStateViolationCode]
    TERMS_DEADLINE: ClassVar[MarketStateViolationCode]
    TERMS_CHALLENGE_WINDOW: ClassVar[MarketStateViolationCode]
    TERMS_RECIPE_REFS: ClassVar[MarketStateViolationCode]
    TERMS_VERIFIER_REFS: ClassVar[MarketStateViolationCode]
    PHASE_TYPE: ClassVar[MarketStateViolationCode]
    ESCROW_TYPE: ClassVar[MarketStateViolationCode]
    SUBMISSION_TYPE: ClassVar[MarketStateViolationCode]
    SUBMISSION_ID: ClassVar[MarketStateViolationCode]
    SUBMISSION_SUBMITTER_REF: ClassVar[MarketStateViolationCode]
    SUBMISSION_RECIPE_REF: ClassVar[MarketStateViolationCode]
    SUBMISSION_VERIFIER_REF: ClassVar[MarketStateViolationCode]
    SUBMISSION_EVIDENCE_REFS: ClassVar[MarketStateViolationCode]
    SUBMISSION_ARTIFACT_REFS: ClassVar[MarketStateViolationCode]
    SUBMISSION_SUBMITTED_AT: ClassVar[MarketStateViolationCode]
    SUBMISSION_STATUS: ClassVar[MarketStateViolationCode]
    SUBMISSION_BOND: ClassVar[MarketStateViolationCode]
    SUBMISSION_RECEIPT_REF: ClassVar[MarketStateViolationCode]
    CHALLENGE_TYPE: ClassVar[MarketStateViolationCode]
    CHALLENGE_ID: ClassVar[MarketStateViolationCode]
    CHALLENGE_SUBMISSION_ID: ClassVar[MarketStateViolationCode]
    CHALLENGE_CHALLENGER_REF: ClassVar[MarketStateViolationCode]
    CHALLENGE_FINDING_KIND: ClassVar[MarketStateViolationCode]
    CHALLENGE_EVIDENCE_REFS: ClassVar[MarketStateViolationCode]
    CHALLENGE_OPENED_AT: ClassVar[MarketStateViolationCode]
    CHALLENGE_STATUS: ClassVar[MarketStateViolationCode]
    CHALLENGE_DEPOSIT: ClassVar[MarketStateViolationCode]
    CHALLENGE_RECEIPT_REF: ClassVar[MarketStateViolationCode]
    DUPLICATE_SUBMISSION_ID: ClassVar[MarketStateViolationCode]
    DUPLICATE_CHALLENGE_ID: ClassVar[MarketStateViolationCode]
    CHALLENGE_UNKNOWN_SUBMISSION: ClassVar[MarketStateViolationCode]
    DUPLICATE_PAYABLE_SUBMISSION_ID: ClassVar[MarketStateViolationCode]
    PAYABLE_UNKNOWN_SUBMISSION: ClassVar[MarketStateViolationCode]
    PAYABLE_SUBMISSION_NOT_VERIFIED: ClassVar[MarketStateViolationCode]
    PAYABLE_IDS_FORMAT: ClassVar[MarketStateViolationCode]
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
    PROCESSED_COMMAND_IDS_FORMAT: ClassVar[MarketStateViolationCode]
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
        ("TERMS_BOUNTY_ID", "terms_bounty_id"),
        ("TERMS_SPONSOR_REF", "terms_sponsor_ref"),
        ("TERMS_CLAIM_REF", "terms_claim_ref"),
        ("TERMS_CONTEXT_REF", "terms_context_ref"),
        ("TERMS_REWARD", "terms_reward"),
        ("TERMS_MIN_BOND", "terms_min_bond"),
        ("TERMS_DEADLINE", "terms_deadline"),
        ("TERMS_CHALLENGE_WINDOW", "terms_challenge_window"),
        ("TERMS_RECIPE_REFS", "terms_recipe_refs"),
        ("TERMS_VERIFIER_REFS", "terms_verifier_refs"),
        ("PHASE_TYPE", "phase_type"),
        ("ESCROW_TYPE", "escrow_type"),
        ("SUBMISSION_TYPE", "submission_type"),
        ("SUBMISSION_ID", "submission_id"),
        ("SUBMISSION_SUBMITTER_REF", "submission_submitter_ref"),
        ("SUBMISSION_RECIPE_REF", "submission_recipe_ref"),
        ("SUBMISSION_VERIFIER_REF", "submission_verifier_ref"),
        ("SUBMISSION_EVIDENCE_REFS", "submission_evidence_refs"),
        ("SUBMISSION_ARTIFACT_REFS", "submission_artifact_refs"),
        ("SUBMISSION_SUBMITTED_AT", "submission_submitted_at"),
        ("SUBMISSION_STATUS", "submission_status"),
        ("SUBMISSION_BOND", "submission_bond"),
        ("SUBMISSION_RECEIPT_REF", "submission_receipt_ref"),
        ("CHALLENGE_TYPE", "challenge_type"),
        ("CHALLENGE_ID", "challenge_id"),
        ("CHALLENGE_SUBMISSION_ID", "challenge_submission_id"),
        ("CHALLENGE_CHALLENGER_REF", "challenge_challenger_ref"),
        ("CHALLENGE_FINDING_KIND", "challenge_finding_kind"),
        ("CHALLENGE_EVIDENCE_REFS", "challenge_evidence_refs"),
        ("CHALLENGE_OPENED_AT", "challenge_opened_at"),
        ("CHALLENGE_STATUS", "challenge_status"),
        ("CHALLENGE_DEPOSIT", "challenge_deposit"),
        ("CHALLENGE_RECEIPT_REF", "challenge_receipt_ref"),
        ("DUPLICATE_SUBMISSION_ID", "duplicate_submission_id"),
        ("DUPLICATE_CHALLENGE_ID", "duplicate_challenge_id"),
        ("CHALLENGE_UNKNOWN_SUBMISSION", "challenge_unknown_submission"),
        ("DUPLICATE_PAYABLE_SUBMISSION_ID", "duplicate_payable_submission_id"),
        ("PAYABLE_UNKNOWN_SUBMISSION", "payable_unknown_submission"),
        ("PAYABLE_SUBMISSION_NOT_VERIFIED", "payable_submission_not_verified"),
        ("PAYABLE_IDS_FORMAT", "payable_ids_format"),
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
        ("PROCESSED_COMMAND_IDS_FORMAT", "processed_command_ids_format"),
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
    _check_types_and_terms(state, violations)
    if violations:
        return tuple(violations)
    _check_submission_fields(state, violations)
    if violations:
        return tuple(violations)
    _check_challenge_fields(state, violations)
    if violations:
        return tuple(violations)
    _check_collection_fields(state, violations)
    _check_uniqueness(state, violations)
    _check_references(state, violations)
    _check_payable(state, violations)
    _check_challenge_invariants(state, violations)
    _check_phase_invariants(state, violations)
    _check_terminal_invariants(state, violations)
    return tuple(violations)


def _v(code: MarketStateViolationCode, field_path: str, detail: str) -> MarketStateViolation:
    return MarketStateViolation(code=code, field_path=field_path, detail=detail)


def _valid_id(value: object) -> bool:
    return type(value) is str and bool(_ID_RE.fullmatch(value))


def _valid_ref(value: object) -> bool:
    return type(value) is str and bool(_REF_RE.fullmatch(value))


def _valid_ref_tuple(value: object) -> bool:
    return isinstance(value, tuple) and all(_valid_ref(item) for item in value)


def _valid_ref_frozenset(value: object, *, non_empty: bool = False) -> bool:
    return (
        isinstance(value, frozenset)
        and (bool(value) or not non_empty)
        and all(_valid_ref(item) for item in value)
    )


def _non_neg_int(value: object) -> bool:
    return type(value) is int and not isinstance(value, bool) and value >= 0


def _check_types_and_terms(state: BountyState, out: list[MarketStateViolation]) -> None:
    if type(state.terms) is not BountyTerms:
        out.append(_v(MarketStateViolationCode.TERMS_TYPE, "$.terms", "must be BountyTerms"))
        return
    terms = state.terms
    if not _valid_id(terms.bounty_id):
        out.append(_v(MarketStateViolationCode.TERMS_BOUNTY_ID, "$.terms.bounty_id", "invalid id format"))
    if not (isinstance(terms.sponsor_ref, str) and terms.sponsor_ref):
        out.append(_v(MarketStateViolationCode.TERMS_SPONSOR_REF, "$.terms.sponsor_ref", "must be non-empty string"))
    if not _valid_ref(terms.claim_ref):
        out.append(_v(MarketStateViolationCode.TERMS_CLAIM_REF, "$.terms.claim_ref", "invalid ref format"))
    if terms.context_ref is not None and not _valid_ref(terms.context_ref):
        out.append(_v(MarketStateViolationCode.TERMS_CONTEXT_REF, "$.terms.context_ref", "must be null or valid ref"))
    if not (type(terms.reward) is Amount and terms.reward.atoms > 0):
        out.append(_v(MarketStateViolationCode.TERMS_REWARD, "$.terms.reward", "must be positive Amount"))
    if type(terms.minimum_submission_bond) is not Amount:
        out.append(_v(MarketStateViolationCode.TERMS_MIN_BOND, "$.terms.minimum_submission_bond", "must be Amount"))
    if not _non_neg_int(terms.deadline_epoch_s):
        out.append(_v(MarketStateViolationCode.TERMS_DEADLINE, "$.terms.deadline_epoch_s", "must be non-negative int"))
    if not _non_neg_int(terms.challenge_window_seconds):
        out.append(_v(MarketStateViolationCode.TERMS_CHALLENGE_WINDOW, "$.terms.challenge_window_seconds", "must be non-negative int"))
    if not _valid_ref_frozenset(terms.accepted_recipe_refs, non_empty=True):
        out.append(_v(MarketStateViolationCode.TERMS_RECIPE_REFS, "$.terms.accepted_recipe_refs", "must be non-empty frozenset of valid refs"))
    if not _valid_ref_frozenset(terms.accepted_verifier_refs, non_empty=True):
        out.append(_v(MarketStateViolationCode.TERMS_VERIFIER_REFS, "$.terms.accepted_verifier_refs", "must be non-empty frozenset of valid refs"))
    if type(state.phase) is not BountyPhase:
        out.append(_v(MarketStateViolationCode.PHASE_TYPE, "$.phase", "must be BountyPhase"))
    if type(state.escrow_locked) is not Amount:
        out.append(_v(MarketStateViolationCode.ESCROW_TYPE, "$.escrow_locked", "must be Amount"))


def _check_submission_fields(state: BountyState, out: list[MarketStateViolation]) -> None:
    if not isinstance(state.submissions, tuple) or any(
        type(value) is not SubmissionState for value in state.submissions
    ):
        out.append(_v(MarketStateViolationCode.SUBMISSION_TYPE, "$.submissions", "must be tuple of SubmissionState"))
        return
    for i, sub in enumerate(state.submissions):
        path = f"$.submissions[{i}]"
        if not _valid_id(sub.submission_id):
            out.append(_v(MarketStateViolationCode.SUBMISSION_ID, f"{path}.submission_id", "invalid id format"))
        if not (isinstance(sub.submitter_ref, str) and sub.submitter_ref):
            out.append(_v(MarketStateViolationCode.SUBMISSION_SUBMITTER_REF, f"{path}.submitter_ref", "must be non-empty string"))
        if not _valid_ref(sub.recipe_ref):
            out.append(_v(MarketStateViolationCode.SUBMISSION_RECIPE_REF, f"{path}.recipe_ref", "invalid ref format"))
        if not _valid_ref(sub.verifier_ref):
            out.append(_v(MarketStateViolationCode.SUBMISSION_VERIFIER_REF, f"{path}.verifier_ref", "invalid ref format"))
        if not _valid_ref_tuple(sub.evidence_refs):
            out.append(_v(MarketStateViolationCode.SUBMISSION_EVIDENCE_REFS, f"{path}.evidence_refs", "must be tuple of valid refs"))
        if not _valid_ref_tuple(sub.artifact_refs):
            out.append(_v(MarketStateViolationCode.SUBMISSION_ARTIFACT_REFS, f"{path}.artifact_refs", "must be tuple of valid refs"))
        if not _non_neg_int(sub.submitted_at):
            out.append(_v(MarketStateViolationCode.SUBMISSION_SUBMITTED_AT, f"{path}.submitted_at", "must be non-negative int"))
        if type(sub.status) is not SubmissionStatus:
            out.append(_v(MarketStateViolationCode.SUBMISSION_STATUS, f"{path}.status", "must be SubmissionStatus"))
        if type(sub.bond_locked) is not Amount:
            out.append(_v(MarketStateViolationCode.SUBMISSION_BOND, f"{path}.bond_locked", "must be Amount"))
        if sub.verifier_receipt_ref is not None and not _valid_ref(sub.verifier_receipt_ref):
            out.append(_v(MarketStateViolationCode.SUBMISSION_RECEIPT_REF, f"{path}.verifier_receipt_ref", "must be null or valid ref"))


def _check_challenge_fields(state: BountyState, out: list[MarketStateViolation]) -> None:
    if not isinstance(state.challenges, tuple) or any(
        type(value) is not ChallengeState for value in state.challenges
    ):
        out.append(_v(MarketStateViolationCode.CHALLENGE_TYPE, "$.challenges", "must be tuple of ChallengeState"))
        return
    for i, ch in enumerate(state.challenges):
        path = f"$.challenges[{i}]"
        if not _valid_id(ch.challenge_id):
            out.append(_v(MarketStateViolationCode.CHALLENGE_ID, f"{path}.challenge_id", "invalid id format"))
        if not _valid_id(ch.submission_id):
            out.append(_v(MarketStateViolationCode.CHALLENGE_SUBMISSION_ID, f"{path}.submission_id", "invalid id format"))
        if not (isinstance(ch.challenger_ref, str) and ch.challenger_ref):
            out.append(_v(MarketStateViolationCode.CHALLENGE_CHALLENGER_REF, f"{path}.challenger_ref", "must be non-empty string"))
        if not (isinstance(ch.finding_kind, str) and ch.finding_kind):
            out.append(_v(MarketStateViolationCode.CHALLENGE_FINDING_KIND, f"{path}.finding_kind", "must be non-empty string"))
        if not _valid_ref_tuple(ch.evidence_refs):
            out.append(_v(MarketStateViolationCode.CHALLENGE_EVIDENCE_REFS, f"{path}.evidence_refs", "must be tuple of valid refs"))
        if not _non_neg_int(ch.opened_at):
            out.append(_v(MarketStateViolationCode.CHALLENGE_OPENED_AT, f"{path}.opened_at", "must be non-negative int"))
        if type(ch.status) is not ChallengeStatus:
            out.append(_v(MarketStateViolationCode.CHALLENGE_STATUS, f"{path}.status", "must be ChallengeStatus"))
        if type(ch.deposit_locked) is not Amount:
            out.append(_v(MarketStateViolationCode.CHALLENGE_DEPOSIT, f"{path}.deposit_locked", "must be Amount"))
        if ch.verifier_receipt_ref is not None and not _valid_ref(ch.verifier_receipt_ref):
            out.append(_v(MarketStateViolationCode.CHALLENGE_RECEIPT_REF, f"{path}.verifier_receipt_ref", "must be null or valid ref"))


def _check_collection_fields(state: BountyState, out: list[MarketStateViolation]) -> None:
    if not isinstance(state.payable_submission_ids, tuple) or not all(
        _valid_id(item) for item in state.payable_submission_ids
    ):
        out.append(_v(MarketStateViolationCode.PAYABLE_IDS_FORMAT, "$.payable_submission_ids", "must be tuple of valid ids"))
    if state.settlement_ref is not None and (not isinstance(state.settlement_ref, str) or not state.settlement_ref):
        out.append(_v(MarketStateViolationCode.SETTLEMENT_REF_TYPE, "$.settlement_ref", "must be null or non-empty string"))
    if not isinstance(state.processed_command_ids, frozenset):
        out.append(_v(MarketStateViolationCode.PROCESSED_COMMAND_IDS_TYPE, "$.processed_command_ids", "must be frozenset"))
    elif not all(_valid_id(cid) for cid in state.processed_command_ids):
        out.append(_v(MarketStateViolationCode.PROCESSED_COMMAND_IDS_FORMAT, "$.processed_command_ids", "must contain valid ids"))


def _check_uniqueness(state: BountyState, out: list[MarketStateViolation]) -> None:
    submission_ids = [value.submission_id for value in state.submissions]
    if len(set(submission_ids)) != len(submission_ids):
        out.append(_v(MarketStateViolationCode.DUPLICATE_SUBMISSION_ID, "$.submissions", "ids must be unique"))
    challenge_ids = [value.challenge_id for value in state.challenges]
    if len(set(challenge_ids)) != len(challenge_ids):
        out.append(_v(MarketStateViolationCode.DUPLICATE_CHALLENGE_ID, "$.challenges", "ids must be unique"))
    payable_ids = list(state.payable_submission_ids)
    if len(set(payable_ids)) != len(payable_ids):
        out.append(_v(MarketStateViolationCode.DUPLICATE_PAYABLE_SUBMISSION_ID, "$.payable_submission_ids", "must be unique"))


def _check_references(state: BountyState, out: list[MarketStateViolation]) -> None:
    submissions_by_id = {value.submission_id: value for value in state.submissions}
    for challenge in state.challenges:
        if challenge.submission_id not in submissions_by_id:
            out.append(_v(
                MarketStateViolationCode.CHALLENGE_UNKNOWN_SUBMISSION,
                f"$.challenges[{challenge.challenge_id}]",
                f"references unknown submission {challenge.submission_id}",
            ))


def _check_payable(state: BountyState, out: list[MarketStateViolation]) -> None:
    submissions_by_id = {value.submission_id: value for value in state.submissions}
    for submission_id in state.payable_submission_ids:
        submission = submissions_by_id.get(submission_id)
        if submission is None:
            out.append(_v(
                MarketStateViolationCode.PAYABLE_UNKNOWN_SUBMISSION,
                f"$.payable_submission_ids[{submission_id}]",
                "references unknown submission",
            ))
        elif submission.status is not SubmissionStatus.VERIFIED:
            out.append(_v(
                MarketStateViolationCode.PAYABLE_SUBMISSION_NOT_VERIFIED,
                f"$.payable_submission_ids[{submission_id}]",
                f"submission status is {submission.status.value}, not verified",
            ))


def _check_challenge_invariants(state: BountyState, out: list[MarketStateViolation]) -> None:
    open_challenges = [value for value in state.challenges if value.status is ChallengeStatus.OPEN]
    open_subjects = [value.submission_id for value in open_challenges]
    if len(set(open_subjects)) != len(open_subjects):
        out.append(_v(MarketStateViolationCode.MULTIPLE_OPEN_CHALLENGES, "$.challenges", "multiple open challenges per submission"))
    if open_challenges and state.phase is not BountyPhase.OPEN:
        out.append(_v(MarketStateViolationCode.OPEN_CHALLENGE_OUTSIDE_OPEN_PHASE, "$.phase", "open challenges exist outside OPEN phase"))
    for challenge in open_challenges:
        if challenge.deposit_locked.atoms <= 0:
            out.append(_v(
                MarketStateViolationCode.OPEN_CHALLENGE_WITHOUT_DEPOSIT,
                f"$.challenges[{challenge.challenge_id}]",
                "open challenge has no locked deposit",
            ))
    for challenge in state.challenges:
        if challenge.status is not ChallengeStatus.OPEN and challenge.deposit_locked.atoms != 0:
            out.append(_v(
                MarketStateViolationCode.RESOLVED_CHALLENGE_RETAINS_DEPOSIT,
                f"$.challenges[{challenge.challenge_id}]",
                "resolved challenge retains deposit",
            ))
    for submission in state.submissions:
        if submission.status is SubmissionStatus.REJECTED and submission.bond_locked.atoms != 0:
            out.append(_v(
                MarketStateViolationCode.REJECTED_SUBMISSION_RETAINS_BOND,
                f"$.submissions[{submission.submission_id}]",
                "rejected submission retains bond",
            ))


def _check_phase_invariants(state: BountyState, out: list[MarketStateViolation]) -> None:
    phase = state.phase
    payable_ids = state.payable_submission_ids
    if phase is BountyPhase.DRAFT:
        if state.escrow_locked.atoms != 0:
            out.append(_v(MarketStateViolationCode.DRAFT_HAS_ESCROW, "$.escrow_locked", "draft must have zero escrow"))
        if state.submissions or state.challenges or payable_ids or state.settlement_ref is not None:
            out.append(_v(MarketStateViolationCode.DRAFT_HAS_ACTIVITY, "$", "draft must have no activity"))
    elif phase is BountyPhase.OPEN:
        if state.escrow_locked.atoms <= 0:
            out.append(_v(MarketStateViolationCode.OPEN_WITHOUT_ESCROW, "$.escrow_locked", "open must have positive escrow"))
        if payable_ids:
            out.append(_v(MarketStateViolationCode.OPEN_HAS_PAYABLE_IDS, "$.payable_submission_ids", "open must have no payable ids"))
        if state.settlement_ref is not None:
            out.append(_v(MarketStateViolationCode.OPEN_HAS_SETTLEMENT, "$.settlement_ref", "open must have no settlement"))
    elif phase is BountyPhase.PAYABLE:
        if state.escrow_locked.atoms <= 0:
            out.append(_v(MarketStateViolationCode.PAYABLE_WITHOUT_ESCROW, "$.escrow_locked", "payable must have positive escrow"))
        if not payable_ids:
            out.append(_v(MarketStateViolationCode.PAYABLE_WITHOUT_SUBMISSION, "$.payable_submission_ids", "payable must have at least one submission"))
        if any(value.status is ChallengeStatus.OPEN for value in state.challenges):
            out.append(_v(MarketStateViolationCode.PAYABLE_WITH_OPEN_CHALLENGE, "$.challenges", "payable must have no open challenges"))
    elif phase is BountyPhase.SETTLED:
        if state.escrow_locked.atoms != 0:
            out.append(_v(MarketStateViolationCode.SETTLED_RETAINS_ESCROW, "$.escrow_locked", "settled must have zero escrow"))
        if not payable_ids:
            out.append(_v(MarketStateViolationCode.SETTLED_WITHOUT_PAYABLE_SUBMISSION, "$.payable_submission_ids", "settled must reference payable submissions"))
        if not state.settlement_ref:
            out.append(_v(MarketStateViolationCode.SETTLED_WITHOUT_RECEIPT, "$.settlement_ref", "settled must have a settlement ref"))
    elif phase is BountyPhase.EXPIRED:
        if state.escrow_locked.atoms != 0:
            out.append(_v(MarketStateViolationCode.EXPIRED_RETAINS_ESCROW, "$.escrow_locked", "expired must have zero escrow"))
        if payable_ids:
            out.append(_v(MarketStateViolationCode.EXPIRED_HAS_PAYABLE_IDS, "$.payable_submission_ids", "expired must have no payable ids"))
    elif phase is BountyPhase.CANCELED:
        if state.escrow_locked.atoms != 0:
            out.append(_v(MarketStateViolationCode.CANCELED_RETAINS_ESCROW, "$.escrow_locked", "canceled must have zero escrow"))
        if state.submissions or state.challenges or payable_ids:
            out.append(_v(MarketStateViolationCode.CANCELED_HAS_ACTIVITY, "$", "canceled must have no activity"))


def _check_terminal_invariants(state: BountyState, out: list[MarketStateViolation]) -> None:
    terminal = state.phase in {BountyPhase.SETTLED, BountyPhase.EXPIRED, BountyPhase.CANCELED}
    if not terminal:
        if state.settlement_ref is not None:
            out.append(_v(MarketStateViolationCode.NON_SETTLED_HAS_SETTLEMENT, "$.settlement_ref", "non-settled state has settlement ref"))
        return
    if any(value.bond_locked.atoms != 0 for value in state.submissions):
        out.append(_v(MarketStateViolationCode.TERMINAL_RETAINS_BOND, "$.submissions", "terminal state retains submission bond"))
    if any(value.deposit_locked.atoms != 0 for value in state.challenges):
        out.append(_v(MarketStateViolationCode.TERMINAL_RETAINS_DEPOSIT, "$.challenges", "terminal state retains challenge deposit"))
    if any(value.status is ChallengeStatus.OPEN for value in state.challenges):
        out.append(_v(MarketStateViolationCode.TERMINAL_HAS_OPEN_CHALLENGE, "$.challenges", "terminal state has open challenge"))
