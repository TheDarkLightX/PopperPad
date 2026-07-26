from __future__ import annotations

from dataclasses import fields, replace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from popperpad.core.market import (
    REJECTION_PRECEDENCE,
    AdvanceBounty,
    BountyPhase,
    BountyState,
    BountyTerms,
    CancelBounty,
    ChallengeStatus,
    ChallengeVerifierStatement,
    ChallengeVerdict,
    MarketEvidence,
    MarketPolicy,
    OpenBounty,
    OpenChallenge,
    Payout,
    ResolveChallenge,
    SettleBounty,
    SubmissionStatus,
    SubmissionVerifierStatement,
    SubmissionVerdict,
    SubmitCandidate,
    VerifierReceipt,
    VerifySubmission,
    apply_market_command as apply_market_command_core,
    initial_bounty,
    market_policy_hash,
    market_state_hash,
    verifier_receipt_ref,
    verifier_statement_signing_bytes,
)
from popperpad.core.result import Accept, CommittedFailure, Reject
from popperpad.core.values import Amount
from popperpad.core.verifier import ed25519_verifier_ref


def R(char: str) -> str:
    return "sha256:" + char * 64


_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
_PUBLIC_KEY = _PRIVATE_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)
VERIFIER_REF = ed25519_verifier_ref(_PUBLIC_KEY)


def _sign_statement(
    statement: SubmissionVerifierStatement | ChallengeVerifierStatement,
) -> VerifierReceipt:
    return VerifierReceipt(
        statement=statement,
        public_key=_PUBLIC_KEY,
        signature=_PRIVATE_KEY.sign(verifier_statement_signing_bytes(statement)),
    )


def _evidence_for(
    state: BountyState,
    command: object,
    market_policy: MarketPolicy,
) -> tuple[object, MarketEvidence]:
    if type(command) is VerifySubmission:
        submission = next(
            (item for item in state.submissions if item.submission_id == command.submission_id),
            None,
        )
        if submission is None:
            return command, MarketEvidence()
        statement = SubmissionVerifierStatement(
            pre_state_hash=market_state_hash(state),
            policy_hash=market_policy_hash(market_policy),
            bounty_id=state.terms.bounty_id,
            claim_ref=state.terms.claim_ref,
            context_ref=state.terms.context_ref,
            submission_id=submission.submission_id,
            recipe_ref=submission.recipe_ref,
            evidence_refs=submission.evidence_refs,
            artifact_refs=submission.artifact_refs,
            outcome=(
                SubmissionVerdict.ACCEPTED
                if command.accepted
                else SubmissionVerdict.REJECTED
            ),
        )
        receipt = _sign_statement(statement)
        return (
            replace(command, verifier_receipt_ref=verifier_receipt_ref(receipt)),
            MarketEvidence((receipt,)),
        )
    if type(command) is ResolveChallenge:
        challenge = next(
            (item for item in state.challenges if item.challenge_id == command.challenge_id),
            None,
        )
        if challenge is None:
            return command, MarketEvidence()
        statement = ChallengeVerifierStatement(
            pre_state_hash=market_state_hash(state),
            policy_hash=market_policy_hash(market_policy),
            bounty_id=state.terms.bounty_id,
            claim_ref=state.terms.claim_ref,
            context_ref=state.terms.context_ref,
            challenge_id=challenge.challenge_id,
            submission_id=challenge.submission_id,
            finding_kind=challenge.finding_kind,
            evidence_refs=challenge.evidence_refs,
            outcome=(
                ChallengeVerdict.UPHELD
                if command.upheld
                else ChallengeVerdict.REJECTED
            ),
        )
        receipt = _sign_statement(statement)
        return (
            replace(command, verifier_receipt_ref=verifier_receipt_ref(receipt)),
            MarketEvidence((receipt,)),
        )
    return command, MarketEvidence()


def apply_market_command(
    state: BountyState,
    command: object,
    market_policy: MarketPolicy,
):
    bound_command, evidence = _evidence_for(state, command, market_policy)
    return apply_market_command_core(
        state,
        bound_command,  # type: ignore[arg-type]
        market_policy,
        evidence,
    )


def terms() -> BountyTerms:
    return BountyTerms(
        bounty_id="bounty-1",
        sponsor_ref="did:example:sponsor",
        claim_ref=R("a"),
        context_ref=R("b"),
        reward=Amount(1_000),
        minimum_submission_bond=Amount(100),
        deadline_epoch_s=1_000,
        challenge_window_seconds=100,
        accepted_recipe_refs=frozenset({R("c")}),
        accepted_verifier_refs=frozenset({VERIFIER_REF}),
    )


def policy() -> MarketPolicy:
    return MarketPolicy(
        minimum_bounty=Amount(1_000),
        minimum_submission_bond=Amount(100),
        minimum_challenge_deposit=Amount(50),
        slashable_findings=frozenset(
            {
                "unavailable_artifact",
                "invalid_signature",
                "malformed_commitment",
                "duplicate_as_novel",
                "scope_mutation",
                "fake_attestation",
            }
        ),
        challenge_resolution_seconds=100,
    )


def opened_state() -> BountyState:
    decision = apply_market_command(
        initial_bounty(terms()),
        OpenBounty("cmd-open", "did:example:sponsor", Amount(1_000), 100),
        policy(),
    )
    assert isinstance(decision, Accept)
    return decision.next_state


def submitted_state() -> BountyState:
    decision = apply_market_command(
        opened_state(),
        SubmitCandidate(
            command_id="cmd-submit",
            submission_id="submission-1",
            submitter_ref="did:example:refuter",
            recipe_ref=R("c"),
            verifier_ref=VERIFIER_REF,
            evidence_refs=(R("e"),),
            artifact_refs=(R("f"),),
            bond=Amount(100),
            now_epoch_s=500,
        ),
        policy(),
    )
    assert isinstance(decision, Accept)
    return decision.next_state


def verified_state() -> BountyState:
    decision = apply_market_command(
        submitted_state(),
        VerifySubmission(
            "cmd-verify",
            "submission-1",
            VERIFIER_REF,
            R("1"),
            True,
            700,
        ),
        policy(),
    )
    assert isinstance(decision, Accept)
    return decision.next_state


def test_happy_path_is_exact_deterministic_and_conservative() -> None:
    state = initial_bounty(terms())
    open_command = OpenBounty("cmd-open", "did:example:sponsor", Amount(1_000), 100)
    first = apply_market_command(state, open_command, policy())
    second = apply_market_command(state, open_command, policy())
    assert first == second
    assert isinstance(first, Accept)
    assert first.next_state.phase is BountyPhase.OPEN
    assert [(effect.kind, effect.amount.atoms) for effect in first.effects] == [("lock_escrow", 1_000)]

    submitted = apply_market_command(
        first.next_state,
        SubmitCandidate(
            "cmd-submit",
            "submission-1",
            "did:example:refuter",
            R("c"),
            VERIFIER_REF,
            (R("e"),),
            (R("f"),),
            Amount(100),
            500,
        ),
        policy(),
    )
    assert isinstance(submitted, Accept)
    assert submitted.effects[0].kind == "lock_submission_bond"

    verified = apply_market_command(
        submitted.next_state,
        VerifySubmission("cmd-verify", "submission-1", VERIFIER_REF, R("1"), True, 700),
        policy(),
    )
    assert isinstance(verified, Accept)
    assert verified.next_state.submissions[0].status is SubmissionStatus.VERIFIED

    payable = apply_market_command(
        verified.next_state,
        AdvanceBounty("cmd-advance", 1_101),
        policy(),
    )
    assert isinstance(payable, Accept)
    assert payable.next_state.phase is BountyPhase.PAYABLE
    assert payable.next_state.payable_submission_ids == ("submission-1",)

    settled = apply_market_command(
        payable.next_state,
        SettleBounty(
            command_id="cmd-settle",
            settlement_ref="chain:tx:1",
            payouts=(Payout("did:example:refuter", "submission-1", Amount(1_000)),),
            now_epoch_s=1_102,
        ),
        policy(),
    )
    assert isinstance(settled, Accept)
    assert settled.next_state.phase is BountyPhase.SETTLED
    assert settled.next_state.escrow_locked == Amount.zero()
    assert settled.next_state.submissions[0].bond_locked == Amount.zero()
    assert sum(effect.amount.atoms for effect in settled.effects if effect.kind == "payout") == 1_000
    assert sum(effect.amount.atoms for effect in settled.effects if effect.kind == "refund_submission_bond") == 100
    assert settled.receipt.state_hash.startswith("sha256:")
    assert settled.receipt.effect_plan_hash.startswith("sha256:")


def test_honest_verifier_rejection_is_committed_failure_and_refunds_not_slashes() -> None:
    decision = apply_market_command(
        submitted_state(),
        VerifySubmission("cmd-reject", "submission-1", VERIFIER_REF, R("1"), False, 700),
        policy(),
    )
    assert isinstance(decision, CommittedFailure)
    assert decision.code == "VERIFIER_REJECTED"
    assert decision.next_state.submissions[0].status is SubmissionStatus.REJECTED
    assert decision.next_state.submissions[0].bond_locked == Amount.zero()
    assert [effect.kind for effect in decision.effects] == ["refund_submission_bond"]
    assert all("slash" not in effect.kind for effect in decision.effects)


def test_shape_valid_receipt_reference_cannot_authorize_verifier_outcome() -> None:
    decision = apply_market_command_core(
        submitted_state(),
        VerifySubmission(
            "cmd-forged-verdict",
            "submission-1",
            VERIFIER_REF,
            R("9"),
            True,
            700,
        ),
        policy(),
        MarketEvidence(),
    )
    assert isinstance(decision, Reject)
    assert decision.code in {"INVALID_EVIDENCE", "MISSING_EVIDENCE"}


def test_invalid_verifier_signature_is_rejected_before_state_change() -> None:
    state = submitted_state()
    command, evidence = _evidence_for(
        state,
        VerifySubmission(
            "cmd-invalid-signature",
            "submission-1",
            VERIFIER_REF,
            R("1"),
            True,
            700,
        ),
        policy(),
    )
    assert type(command) is VerifySubmission
    receipt = evidence.verifier_receipts[0]
    tampered = replace(receipt, signature=b"\x00" * 64)
    command = replace(command, verifier_receipt_ref=verifier_receipt_ref(tampered))

    decision = apply_market_command_core(
        state,
        command,
        policy(),
        MarketEvidence((tampered,)),
    )
    assert isinstance(decision, Reject)
    assert decision.code == "INVALID_EVIDENCE"
    assert state.submissions[0].status is SubmissionStatus.PENDING


def test_invalid_signature_precedes_duplicate_command_and_wrong_phase() -> None:
    state = submitted_state()
    command, evidence = _evidence_for(
        state,
        VerifySubmission(
            "cmd-invalid-evidence-precedence",
            "submission-1",
            VERIFIER_REF,
            R("1"),
            True,
            700,
        ),
        policy(),
    )
    assert type(command) is VerifySubmission
    receipt = evidence.verifier_receipts[0]
    tampered = replace(receipt, signature=b"\x00" * 64)
    bound_command = replace(
        command,
        verifier_receipt_ref=verifier_receipt_ref(tampered),
    )
    invalid_evidence = MarketEvidence((tampered,))

    duplicate_state = replace(
        state,
        processed_command_ids=state.processed_command_ids
        | frozenset({bound_command.command_id}),
    )
    for pre_state in (duplicate_state, initial_bounty(terms())):
        decision = apply_market_command_core(
            pre_state,
            bound_command,
            policy(),
            invalid_evidence,
        )
        assert isinstance(decision, Reject)
        assert decision.code == "INVALID_EVIDENCE"


def test_signed_binding_mismatch_precedes_duplicate_command_and_wrong_phase() -> None:
    state = submitted_state()
    command = VerifySubmission(
        "cmd-invalid-binding-precedence",
        "submission-1",
        VERIFIER_REF,
        R("1"),
        True,
        700,
    )
    bound_command, evidence = _evidence_for(state, command, policy())
    assert type(bound_command) is VerifySubmission
    duplicate_state = replace(
        state,
        processed_command_ids=state.processed_command_ids
        | frozenset({bound_command.command_id}),
    )

    for pre_state in (duplicate_state, initial_bounty(terms())):
        decision = apply_market_command_core(
            pre_state,
            bound_command,
            policy(),
            evidence,
        )
        assert isinstance(decision, Reject)
        assert decision.code == "INVALID_EVIDENCE"

    policy_bound_command, policy_evidence = _evidence_for(
        duplicate_state, command, policy()
    )
    assert type(policy_bound_command) is VerifySubmission
    changed_policy = replace(policy(), version="popperpad/market-policy/v2")
    policy_decision = apply_market_command_core(
        duplicate_state,
        policy_bound_command,
        changed_policy,
        policy_evidence,
    )
    assert isinstance(policy_decision, Reject)
    assert policy_decision.code == "INVALID_EVIDENCE"


def test_missing_receipt_preserves_duplicate_and_phase_precedence() -> None:
    state = submitted_state()
    command = VerifySubmission(
        "cmd-missing-evidence-precedence",
        "submission-1",
        VERIFIER_REF,
        R("9"),
        True,
        700,
    )
    duplicate_state = replace(
        state,
        processed_command_ids=state.processed_command_ids
        | frozenset({command.command_id}),
    )
    duplicate = apply_market_command_core(
        duplicate_state, command, policy(), MarketEvidence()
    )
    assert isinstance(duplicate, Reject)
    assert duplicate.code == "DUPLICATE_COMMAND"

    wrong_phase = apply_market_command_core(
        initial_bounty(terms()), command, policy(), MarketEvidence()
    )
    assert isinstance(wrong_phase, Reject)
    assert wrong_phase.code == "WRONG_PHASE"


@pytest.mark.parametrize(
    "change",
    (
        {"pre_state_hash": R("8")},
        {"policy_hash": R("7")},
        {"submission_id": "another-submission"},
        {"outcome": SubmissionVerdict.REJECTED},
    ),
)
def test_signed_verifier_statement_must_bind_exact_candidate(change: dict[str, object]) -> None:
    state = submitted_state()
    command, evidence = _evidence_for(
        state,
        VerifySubmission(
            "cmd-wrong-binding",
            "submission-1",
            VERIFIER_REF,
            R("1"),
            True,
            700,
        ),
        policy(),
    )
    assert type(command) is VerifySubmission
    statement = evidence.verifier_receipts[0].statement
    assert type(statement) is SubmissionVerifierStatement
    mismatched = _sign_statement(replace(statement, **change))
    command = replace(command, verifier_receipt_ref=verifier_receipt_ref(mismatched))

    decision = apply_market_command_core(
        state,
        command,
        policy(),
        MarketEvidence((mismatched,)),
    )
    assert isinstance(decision, Reject)
    assert decision.code == "INVALID_EVIDENCE"
    assert state.submissions[0].status is SubmissionStatus.PENDING


def test_upheld_protocol_challenge_slashes_only_declared_misconduct() -> None:
    challenged = apply_market_command(
        verified_state(),
        OpenChallenge(
            command_id="cmd-challenge",
            challenge_id="challenge-1",
            submission_id="submission-1",
            challenger_ref="did:example:challenger",
            finding_kind="unavailable_artifact",
            evidence_refs=(R("2"),),
            deposit=Amount(50),
            now_epoch_s=800,
        ),
        policy(),
    )
    assert isinstance(challenged, Accept)
    resolved = apply_market_command(
        challenged.next_state,
        ResolveChallenge(
            "cmd-resolve",
            "challenge-1",
            VERIFIER_REF,
            R("3"),
            True,
            850,
        ),
        policy(),
    )
    assert isinstance(resolved, Accept)
    assert [effect.kind for effect in resolved.effects] == [
        "refund_challenge_deposit",
        "slash_submission_bond",
    ]
    assert resolved.next_state.submissions[0].status is SubmissionStatus.REJECTED
    assert resolved.next_state.submissions[0].bond_locked == Amount.zero()


def test_signed_challenge_binding_mismatch_precedes_duplicate_and_phase() -> None:
    challenged = apply_market_command(
        verified_state(),
        OpenChallenge(
            "cmd-challenge-precedence",
            "challenge-precedence",
            "submission-1",
            "did:example:challenger",
            "invalid_signature",
            (R("2"),),
            Amount(50),
            800,
        ),
        policy(),
    )
    assert isinstance(challenged, Accept)
    command = ResolveChallenge(
        "cmd-resolve-precedence",
        "challenge-precedence",
        VERIFIER_REF,
        R("3"),
        True,
        850,
    )
    bound_command, evidence = _evidence_for(
        challenged.next_state, command, policy()
    )
    assert type(bound_command) is ResolveChallenge
    duplicate_state = replace(
        challenged.next_state,
        processed_command_ids=challenged.next_state.processed_command_ids
        | frozenset({bound_command.command_id}),
    )

    for pre_state in (duplicate_state, initial_bounty(terms())):
        decision = apply_market_command_core(
            pre_state, bound_command, policy(), evidence
        )
        assert isinstance(decision, Reject)
        assert decision.code == "INVALID_EVIDENCE"



def test_rejected_challenge_is_committed_failure_and_slashes_challenger_deposit() -> None:
    challenged = apply_market_command(
        verified_state(),
        OpenChallenge(
            "cmd-challenge",
            "challenge-1",
            "submission-1",
            "did:example:challenger",
            "invalid_signature",
            (R("2"),),
            Amount(50),
            800,
        ),
        policy(),
    )
    assert isinstance(challenged, Accept)
    resolved = apply_market_command(
        challenged.next_state,
        ResolveChallenge("cmd-resolve", "challenge-1", VERIFIER_REF, R("3"), False, 850),
        policy(),
    )
    assert isinstance(resolved, CommittedFailure)
    assert resolved.code == "CHALLENGE_REJECTED"
    assert [effect.kind for effect in resolved.effects] == ["slash_challenge_deposit"]


def test_timely_challenge_can_be_resolved_after_window_then_bounty_advances() -> None:
    challenged = apply_market_command(
        verified_state(),
        OpenChallenge(
            "cmd-challenge-at-deadline",
            "challenge-at-deadline",
            "submission-1",
            "did:example:challenger",
            "invalid_signature",
            (R("2"),),
            Amount(50),
            1_100,
        ),
        policy(),
    )
    assert isinstance(challenged, Accept)

    resolved = apply_market_command(
        challenged.next_state,
        ResolveChallenge(
            "cmd-resolve-after-window",
            "challenge-at-deadline",
            VERIFIER_REF,
            R("3"),
            False,
            1_200,
        ),
        policy(),
    )
    assert isinstance(resolved, CommittedFailure)
    assert resolved.code == "CHALLENGE_REJECTED"

    advanced = apply_market_command(
        resolved.next_state,
        AdvanceBounty("cmd-advance-after-resolution", 1_201),
        policy(),
    )
    assert isinstance(advanced, Accept)
    assert advanced.next_state.phase is BountyPhase.PAYABLE


def test_abandoned_challenge_defaults_after_bounded_adjudication_period() -> None:
    challenged = apply_market_command(
        verified_state(),
        OpenChallenge(
            "cmd-abandoned-challenge",
            "abandoned-challenge",
            "submission-1",
            "did:example:challenger",
            "invalid_signature",
            (R("2"),),
            Amount(50),
            1_100,
        ),
        policy(),
    )
    assert isinstance(challenged, Accept)

    still_adjudicable = apply_market_command(
        challenged.next_state,
        AdvanceBounty("cmd-too-early", 1_200),
        policy(),
    )
    assert isinstance(still_adjudicable, Reject)
    assert still_adjudicable.code == "POLICY_MISMATCH"

    advanced = apply_market_command(
        challenged.next_state,
        AdvanceBounty("cmd-timeout-default", 1_201),
        policy(),
    )
    assert isinstance(advanced, Accept)
    assert advanced.next_state.phase is BountyPhase.PAYABLE
    assert advanced.next_state.challenges[0].status is ChallengeStatus.REJECTED
    assert advanced.next_state.challenges[0].deposit_locked == Amount.zero()
    assert [effect.kind for effect in advanced.effects] == ["slash_challenge_deposit"]
    assert advanced.effects[0].metadata["reason"] == "resolution_timeout"

    late_resolution = apply_market_command(
        challenged.next_state,
        ResolveChallenge(
            "cmd-late-resolution",
            "abandoned-challenge",
            VERIFIER_REF,
            R("3"),
            True,
            1_201,
        ),
        policy(),
    )
    assert isinstance(late_resolution, Reject)
    assert late_resolution.code == "TIME_WINDOW"


def test_no_payable_submission_expires_and_refunds_all_locked_value() -> None:
    state = submitted_state()
    rejected = apply_market_command(
        state,
        VerifySubmission("cmd-reject", "submission-1", VERIFIER_REF, R("1"), False, 700),
        policy(),
    )
    assert isinstance(rejected, CommittedFailure)
    expired = apply_market_command(
        rejected.next_state,
        AdvanceBounty("cmd-expire", 1_101),
        policy(),
    )
    assert isinstance(expired, CommittedFailure)
    assert expired.code == "NO_PAYABLE_SUBMISSION"
    assert expired.next_state.phase is BountyPhase.EXPIRED
    assert expired.next_state.escrow_locked == Amount.zero()
    assert [effect.kind for effect in expired.effects] == ["refund_escrow"]


def test_cancel_before_activity_refunds_escrow() -> None:
    decision = apply_market_command(
        opened_state(),
        CancelBounty("cmd-cancel", "did:example:sponsor", 200),
        policy(),
    )
    assert isinstance(decision, Accept)
    assert decision.next_state.phase is BountyPhase.CANCELED
    assert decision.effects[0].kind == "refund_escrow"
    assert decision.effects[0].amount == Amount(1_000)


def test_rejection_precedence_is_stable_and_rejects_without_state_or_effects() -> None:
    assert REJECTION_PRECEDENCE[:7] == (
        "INVALID_STATE",
        "INVALID_POLICY",
        "INVALID_COMMAND",
        "INVALID_EVIDENCE",
        "DUPLICATE_COMMAND",
        "WRONG_PHASE",
        "TIME_WINDOW",
    )
    command = SubmitCandidate(
        command_id="cmd-submit",
        submission_id="submission-1",
        submitter_ref="did:example:refuter",
        recipe_ref=R("c"),
        verifier_ref=VERIFIER_REF,
        evidence_refs=(),
        artifact_refs=(),
        bond=Amount.zero(),
        now_epoch_s=2_000,
    )
    wrong_phase = apply_market_command(initial_bounty(terms()), command, policy())
    assert isinstance(wrong_phase, Reject)
    assert wrong_phase.code == "WRONG_PHASE"

    opened = opened_state()
    late = apply_market_command(opened, command, policy())
    assert isinstance(late, Reject)
    assert late.code == "TIME_WINDOW"
    assert opened.phase is BountyPhase.OPEN
    assert opened.submissions == ()


def test_unsupported_command_type_returns_typed_rejection() -> None:
    rejected = apply_market_command(initial_bounty(terms()), object(), policy())  # type: ignore[arg-type]
    assert isinstance(rejected, Reject)
    assert rejected.code == "INVALID_COMMAND"


@pytest.mark.parametrize(
    "command",
    (
        OpenBounty(1, "did:example:sponsor", Amount(1_000), 100),  # type: ignore[arg-type]
        VerifySubmission("cmd", "submission-1", VERIFIER_REF, R("1"), 1, 700),  # type: ignore[arg-type]
        SettleBounty("cmd", "chain:tx:1", ("not-a-payout",), 1_200),  # type: ignore[arg-type]
    ),
)
def test_malformed_immutable_command_fields_return_typed_rejection(command: object) -> None:
    rejected = apply_market_command(initial_bounty(terms()), command, policy())  # type: ignore[arg-type]
    assert isinstance(rejected, Reject)
    assert rejected.code == "INVALID_COMMAND"


@pytest.mark.parametrize(
    "state",
    (
        BountyState(terms=terms(), phase="open"),  # type: ignore[arg-type]
        BountyState(terms=terms(), processed_command_ids=frozenset({7})),  # type: ignore[arg-type]
    ),
)
def test_malformed_immutable_state_fields_return_typed_rejection(state: object) -> None:
    rejected = apply_market_command(  # type: ignore[arg-type]
        state,
        OpenBounty("cmd-valid", "did:example:sponsor", Amount(1_000), 100),
        policy(),
    )
    assert isinstance(rejected, Reject)
    assert rejected.code == "INVALID_STATE"


@pytest.mark.parametrize(
    "bad_policy",
    (
        MarketPolicy(
            minimum_bounty="bad",  # type: ignore[arg-type]
            minimum_submission_bond=Amount(100),
            minimum_challenge_deposit=Amount(50),
            slashable_findings=frozenset({"invalid_signature"}),
        ),
        MarketPolicy(
            minimum_bounty=Amount(1_000),
            minimum_submission_bond=Amount(100),
            minimum_challenge_deposit=Amount(50),
            slashable_findings=frozenset({"invalid_signature"}),
            challenge_resolution_seconds="never",  # type: ignore[arg-type]
        ),
    ),
)
def test_malformed_immutable_policy_fields_return_typed_rejection(bad_policy: object) -> None:
    rejected = apply_market_command(  # type: ignore[arg-type]
        initial_bounty(terms()),
        OpenBounty("cmd-valid", "did:example:sponsor", Amount(1_000), 100),
        bad_policy,
    )
    assert isinstance(rejected, Reject)
    assert rejected.code == "INVALID_POLICY"


def test_duplicate_command_is_rejected_before_command_specific_checks() -> None:
    state = opened_state()
    replay = apply_market_command(
        state,
        OpenBounty("cmd-open", "wrong-sponsor", Amount.zero(), 9_999),
        policy(),
    )
    assert isinstance(replay, Reject)
    assert replay.code == "DUPLICATE_COMMAND"


def test_payout_conservation_failure_prevents_settlement() -> None:
    payable = apply_market_command(
        verified_state(),
        AdvanceBounty("cmd-advance", 1_101),
        policy(),
    )
    assert isinstance(payable, Accept)
    rejected = apply_market_command(
        payable.next_state,
        SettleBounty(
            "cmd-settle",
            "chain:tx:1",
            (Payout("did:example:refuter", "submission-1", Amount(999)),),
            1_102,
        ),
        policy(),
    )
    assert isinstance(rejected, Reject)
    assert rejected.code == "CONSERVATION_FAILURE"
    assert payable.next_state.phase is BountyPhase.PAYABLE
    assert payable.next_state.escrow_locked == Amount(1_000)


def test_market_state_cannot_represent_scientific_truth() -> None:
    names = {field.name for field in fields(BountyState)}
    forbidden = {"truth", "claim_status", "supported", "falsified", "verdict"}
    assert names.isdisjoint(forbidden)


def test_constructor_and_transition_own_collection_inputs() -> None:
    recipes = {R("c")}
    verifiers = {VERIFIER_REF}
    source_terms = BountyTerms(
        bounty_id="bounty-owned",
        sponsor_ref="did:example:sponsor",
        claim_ref=R("a"),
        context_ref=None,
        reward=Amount(1_000),
        minimum_submission_bond=Amount(100),
        deadline_epoch_s=1_000,
        challenge_window_seconds=100,
        accepted_recipe_refs=frozenset(recipes),
        accepted_verifier_refs=frozenset(verifiers),
    )
    state = initial_bounty(source_terms)
    recipes.add(R("e"))
    verifiers.add(R("f"))
    assert state.terms.accepted_recipe_refs == frozenset({R("c")})
    assert state.terms.accepted_verifier_refs == frozenset({VERIFIER_REF})


def test_market_constructor_rejects_mutable_collection_aliases() -> None:
    with pytest.raises(TypeError, match="evidence_refs"):
        SubmitCandidate(  # type: ignore[arg-type]
            command_id="cmd-mutable",
            submission_id="submission-mutable",
            submitter_ref="did:example:refuter",
            recipe_ref=R("c"),
            verifier_ref=VERIFIER_REF,
            evidence_refs=[R("e")],
            artifact_refs=(),
            bond=Amount(100),
            now_epoch_s=500,
        )


def test_terms_reject_illegal_states_at_construction() -> None:
    with pytest.raises(ValueError, match="reward"):
        BountyTerms(
            bounty_id="bad",
            sponsor_ref="sponsor",
            claim_ref=R("a"),
            context_ref=None,
            reward=Amount.zero(),
            minimum_submission_bond=Amount(1),
            deadline_epoch_s=100,
            challenge_window_seconds=10,
            accepted_recipe_refs=frozenset({R("c")}),
            accepted_verifier_refs=frozenset({VERIFIER_REF}),
        )


def test_payable_state_rejects_unverified_submission_ids() -> None:
    payable = apply_market_command(
        verified_state(),
        AdvanceBounty("cmd-advance-malformed-payable", 1_101),
        policy(),
    )
    assert isinstance(payable, Accept)
    rejected_submission = replace(
        payable.next_state.submissions[0],
        status=SubmissionStatus.REJECTED,
    )
    malformed = replace(payable.next_state, submissions=(rejected_submission,))
    decision = apply_market_command(
        malformed,
        SettleBounty(
            "cmd-malformed-settle",
            "chain:tx:malformed",
            (Payout("did:example:refuter", "submission-1", Amount(1_000)),),
            1_102,
        ),
        policy(),
    )
    assert isinstance(decision, Reject)
    assert decision.code == "INVALID_STATE"
    assert "payable_submission_not_verified" in decision.details["reason"]


def test_market_state_rejects_duplicate_and_dangling_challenges() -> None:
    challenged = apply_market_command(
        verified_state(),
        OpenChallenge(
            "cmd-challenge-invalid-state",
            "challenge-invalid-state",
            "submission-1",
            "did:example:challenger",
            "invalid_signature",
            (R("2"),),
            Amount(50),
            800,
        ),
        policy(),
    )
    assert isinstance(challenged, Accept)
    challenge = challenged.next_state.challenges[0]

    duplicate = replace(
        challenged.next_state,
        challenges=(challenge, challenge),
    )
    duplicate_decision = apply_market_command(
        duplicate,
        AdvanceBounty("cmd-duplicate-challenge-state", 1_201),
        policy(),
    )
    assert isinstance(duplicate_decision, Reject)
    assert duplicate_decision.code == "INVALID_STATE"
    assert "duplicate_challenge_id" in duplicate_decision.details["reason"]

    dangling = replace(
        challenged.next_state,
        challenges=(replace(challenge, submission_id="missing-submission"),),
    )
    dangling_decision = apply_market_command(
        dangling,
        AdvanceBounty("cmd-dangling-challenge-state", 1_201),
        policy(),
    )
    assert isinstance(dangling_decision, Reject)
    assert dangling_decision.code == "INVALID_STATE"
    assert "challenge_unknown_submission" in dangling_decision.details["reason"]


def test_market_state_rejects_payable_ids_outside_payable_lifecycle() -> None:
    malformed_open = replace(
        verified_state(),
        payable_submission_ids=("submission-1",),
    )
    open_decision = apply_market_command(
        malformed_open,
        AdvanceBounty("cmd-payable-id-in-open-state", 1_101),
        policy(),
    )
    assert isinstance(open_decision, Reject)
    assert open_decision.code == "INVALID_STATE"
    assert "open_has_payable_ids" in open_decision.details["reason"]

    payable = apply_market_command(
        verified_state(),
        AdvanceBounty("cmd-valid-payable-state", 1_101),
        policy(),
    )
    assert isinstance(payable, Accept)
    malformed_payable = replace(payable.next_state, payable_submission_ids=())
    payable_decision = apply_market_command(
        malformed_payable,
        SettleBounty(
            "cmd-empty-payable-state",
            "chain:tx:empty-payable",
            (Payout("did:example:refuter", "submission-1", Amount(1_000)),),
            1_102,
        ),
        policy(),
    )
    assert isinstance(payable_decision, Reject)
    assert payable_decision.code == "INVALID_STATE"
    assert "payable_without_submission" in payable_decision.details["reason"]


def test_market_state_rejects_non_iterable_payable_ids_without_raising() -> None:
    malformed = replace(verified_state(), payable_submission_ids=None)

    decision = apply_market_command(
        malformed,
        AdvanceBounty("cmd-non-iterable-payable-ids", 1_101),
        policy(),
    )

    assert isinstance(decision, Reject)
    assert decision.code == "INVALID_STATE"
    assert "payable_ids_format" in decision.details["reason"]
