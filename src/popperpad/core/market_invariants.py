from __future__ import annotations

from .market import (
    BountyPhase,
    BountyState,
    BountyTerms,
    ChallengeState,
    ChallengeStatus,
    SubmissionState,
    SubmissionStatus,
)
from .values import Amount


def bounty_state_violations(state: BountyState) -> tuple[str, ...]:
    """Project structural market invariants as stable pure values.

    Command-specific policy stays in ``apply_market_command``. This
    projection only describes properties that every representable
    state must satisfy, so formal adapters and audit tools do not
    need effect authority or private shell callbacks.
    """

    violations: list[str] = []
    if type(state) is not BountyState:
        return ("state_type",)
    if type(state.terms) is not BountyTerms:
        violations.append("terms_type")
    if type(state.phase) is not BountyPhase:
        violations.append("phase_type")
    if type(state.escrow_locked) is not Amount:
        violations.append("escrow_type")
    if not isinstance(state.submissions, tuple) or any(
        type(value) is not SubmissionState for value in state.submissions
    ):
        violations.append("submission_type")
        return tuple(sorted(set(violations)))
    if not isinstance(state.challenges, tuple) or any(
        type(value) is not ChallengeState for value in state.challenges
    ):
        violations.append("challenge_type")
        return tuple(sorted(set(violations)))

    submission_ids = tuple(value.submission_id for value in state.submissions)
    challenge_ids = tuple(value.challenge_id for value in state.challenges)
    if len(set(submission_ids)) != len(submission_ids):
        violations.append("duplicate_submission_id")
    if len(set(challenge_ids)) != len(challenge_ids):
        violations.append("duplicate_challenge_id")
    submissions_by_id = {value.submission_id: value for value in state.submissions}
    if any(value.submission_id not in submissions_by_id for value in state.challenges):
        violations.append("challenge_unknown_submission")

    payable_ids = tuple(state.payable_submission_ids)
    if len(set(payable_ids)) != len(payable_ids):
        violations.append("duplicate_payable_submission_id")
    if any(value not in submissions_by_id for value in payable_ids):
        violations.append("payable_unknown_submission")
    if any(
        submissions_by_id[value].status is not SubmissionStatus.VERIFIED
        for value in payable_ids
        if value in submissions_by_id
    ):
        violations.append("payable_submission_not_verified")

    open_challenges = tuple(
        value for value in state.challenges if value.status is ChallengeStatus.OPEN
    )
    open_subjects = tuple(value.submission_id for value in open_challenges)
    if len(set(open_subjects)) != len(open_subjects):
        violations.append("multiple_open_challenges_per_submission")
    if open_challenges and state.phase is not BountyPhase.OPEN:
        violations.append("open_challenge_outside_open_phase")
    if any(value.deposit_locked.atoms <= 0 for value in open_challenges):
        violations.append("open_challenge_without_deposit")
    if any(
        value.status is not ChallengeStatus.OPEN and value.deposit_locked.atoms != 0
        for value in state.challenges
    ):
        violations.append("resolved_challenge_retains_deposit")
    if any(
        value.status is SubmissionStatus.REJECTED and value.bond_locked.atoms != 0
        for value in state.submissions
    ):
        violations.append("rejected_submission_retains_bond")

    if state.phase is BountyPhase.DRAFT:
        if state.escrow_locked.atoms != 0:
            violations.append("draft_has_escrow")
        if state.submissions or state.challenges or payable_ids or state.settlement_ref is not None:
            violations.append("draft_has_activity")
    elif state.phase is BountyPhase.OPEN:
        if state.escrow_locked.atoms <= 0:
            violations.append("open_without_escrow")
        if payable_ids:
            violations.append("open_has_payable_ids")
        if state.settlement_ref is not None:
            violations.append("open_has_settlement")
    elif state.phase is BountyPhase.PAYABLE:
        if state.escrow_locked.atoms <= 0:
            violations.append("payable_without_escrow")
        if not payable_ids:
            violations.append("payable_without_submission")
        if open_challenges:
            violations.append("payable_with_open_challenge")
    elif state.phase is BountyPhase.SETTLED:
        if state.escrow_locked.atoms != 0:
            violations.append("settled_retains_escrow")
        if not payable_ids:
            violations.append("settled_without_payable_submission")
        if not state.settlement_ref:
            violations.append("settled_without_receipt")
    elif state.phase is BountyPhase.EXPIRED:
        if state.escrow_locked.atoms != 0:
            violations.append("expired_retains_escrow")
        if payable_ids:
            violations.append("expired_has_payable_ids")
    elif state.phase is BountyPhase.CANCELED:
        if state.escrow_locked.atoms != 0:
            violations.append("canceled_retains_escrow")
        if state.submissions or state.challenges or payable_ids:
            violations.append("canceled_has_activity")

    if state.phase in {BountyPhase.SETTLED, BountyPhase.EXPIRED, BountyPhase.CANCELED}:
        if any(value.bond_locked.atoms != 0 for value in state.submissions):
            violations.append("terminal_retains_submission_bond")
        if any(value.deposit_locked.atoms != 0 for value in state.challenges):
            violations.append("terminal_retains_challenge_deposit")
        if open_challenges:
            violations.append("terminal_has_open_challenge")
    if state.phase is not BountyPhase.SETTLED and state.settlement_ref is not None:
        violations.append("nonsettled_has_settlement")
    return tuple(sorted(set(violations)))
