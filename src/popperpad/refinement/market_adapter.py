"""Pure market adapter — abstraction relation with finite state enforcement.

This module implements the abstraction relation between the finite
single-slot abstract state and the authoritative PopperPad market core:

- ``project_state`` — concrete BountyState → finite abstract state
- ``concretize_state`` — finite abstract state → concrete BountyState
- ``concretize_command`` — abstract command → concrete MarketCommand
- ``apply_data_adapter`` — the central total deterministic adapter operation

Key enforcement:
- ``expected_pre_state_hash`` is compared before command evaluation (both STEP and VALIDATE_STATE)
- Request binding_hash is validated against the loaded binding
- Binding profile_hash and source_manifest_hash are verified at load time
- Profile-bounded amounts are enforced (escrow <= reward, bond <= bond, deposit <= deposit)
- All profile array fields reject malformed members (no silent filtering)
- The authoritative market receipt's effect_plan_hash is preserved verbatim
- No silent normalization — mismatches return INVALID_INPUT
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.adapter_protocol import (
    ADAPTER_PROTOCOL_VERSION,
    BINDING_SCHEMA,
    InvalidInput,
    InvalidInputCode,
    DataAdapterProfile,
    AdapterBinding,
    AdapterRequest,
    AdapterResponse,
    AdapterDecisionKind,
    AdapterOperation,
    ExecutionContext,
    build_response,
    build_invalid_input_response,
)
from ..core.codec import canonical_hash
from ..core.market import (
    AdvanceBounty,
    BountyPhase,
    BountyState,
    BountyTerms,
    CancelBounty,
    ChallengeState,
    ChallengeStatus,
    ChallengeVerifierStatement,
    ChallengeVerdict,
    MarketCommand,
    MarketEvidence,
    MarketEffect,
    MarketPolicy,
    OpenBounty,
    OpenChallenge,
    Payout,
    ResolveChallenge,
    SettleBounty,
    SubmissionState,
    SubmissionStatus,
    SubmissionVerifierStatement,
    SubmissionVerdict,
    SubmitCandidate,
    VerifierReceipt,
    VerifySubmission,
    apply_market_command,
    verifier_receipt_ref,
)
from ..core.market_invariants import market_state_violations
from ..core.result import Accept, CommittedFailure, Reject
from ..core.values import Amount, DeeplyImmutable, FrozenDict, JsonValue, freeze_json
from .finite_state import (
    AbstractChallengeStatus,
    AbstractCommandKind,
    AbstractPhase,
    AbstractSubmissionStatus,
    COMMAND_SLOTS,
    SingleSlotAbstractCommand,
    SingleSlotAbstractState,
    TimeClass,
    TimeClassOrNone,
    initial_abstract_state,
    validate_state_bounds,
)


STATE_HASH_DOMAIN = "popperpad-market-abstract-state/v1"
_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ZERO_HASH = "sha256:" + "0" * 64


@dataclass(frozen=True, slots=True)
class SingleSlotMarketProfileData(DeeplyImmutable):
    """Parsed market-specific profile data from the semantic_profile payload."""

    terms: BountyTerms
    policy: MarketPolicy
    submission_id: str
    challenge_id: str
    command_ids: FrozenDict[JsonValue]
    sponsor_ref: str
    submitter_ref: str
    challenger_ref: str
    recipe_ref: str
    verifier_ref: str
    evidence_refs: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    verifier_receipt_ref: str
    challenge_evidence_refs: tuple[str, ...]
    challenge_receipt_ref: str
    settlement_ref: str
    time_representatives: FrozenDict[JsonValue]
    reward_atoms: int
    bond_atoms: int
    deposit_atoms: int


def parse_market_profile(semantic: FrozenDict[JsonValue]) -> SingleSlotMarketProfileData:
    """Parse market-specific typed profile from the generic semantic_profile payload.

    Rejects malformed array members — no silent filtering or normalization.
    """

    terms = _parse_terms(semantic)
    policy = _parse_policy(semantic)
    identities = _get_dict(semantic, "identities")
    time_reps_raw = _get_dict(semantic, "time_representatives")
    command_ids_raw = _get_dict(semantic, "command_ids")
    bounds = _get_dict(semantic, "bounds")
    return SingleSlotMarketProfileData(
        terms=terms,
        policy=policy,
        submission_id=_get_str(identities, "submission_id"),
        challenge_id=_get_str(identities, "challenge_id"),
        command_ids=command_ids_raw,
        sponsor_ref=_get_str(identities, "sponsor_ref"),
        submitter_ref=_get_str(identities, "submitter_ref"),
        challenger_ref=_get_str(identities, "challenger_ref"),
        recipe_ref=_get_ref(identities, "recipe_ref"),
        verifier_ref=_get_ref(identities, "verifier_ref"),
        evidence_refs=_get_ref_tuple(identities, "evidence_refs"),
        artifact_refs=_get_ref_tuple(identities, "artifact_refs"),
        verifier_receipt_ref=_get_ref(identities, "verifier_receipt_ref"),
        challenge_evidence_refs=_get_ref_tuple(identities, "challenge_evidence_refs"),
        challenge_receipt_ref=_get_ref(identities, "challenge_receipt_ref"),
        settlement_ref=_get_str(identities, "settlement_ref"),
        time_representatives=time_reps_raw,
        reward_atoms=_get_int(bounds, "reward_atoms"),
        bond_atoms=_get_int(bounds, "bond_atoms"),
        deposit_atoms=_get_int(bounds, "deposit_atoms"),
    )


def _parse_terms(semantic: FrozenDict[JsonValue]) -> BountyTerms:
    terms = _get_dict(semantic, "bounty_terms")
    return BountyTerms(
        bounty_id=_get_str(terms, "bounty_id"),
        sponsor_ref=_get_str(terms, "sponsor_ref"),
        claim_ref=_get_ref(terms, "claim_ref"),
        context_ref=_get_opt_ref(terms, "context_ref"),
        reward=Amount(_get_int(terms, "reward_atoms")),
        minimum_submission_bond=Amount(_get_int(terms, "minimum_submission_bond_atoms")),
        deadline_epoch_s=_get_int(terms, "deadline_epoch_s"),
        challenge_window_seconds=_get_int(terms, "challenge_window_seconds"),
        accepted_recipe_refs=frozenset(_get_ref_tuple(terms, "accepted_recipe_refs")),
        accepted_verifier_refs=frozenset(_get_ref_tuple(terms, "accepted_verifier_refs")),
    )


def _parse_policy(semantic: FrozenDict[JsonValue]) -> MarketPolicy:
    policy = _get_dict(semantic, "market_policy")
    return MarketPolicy(
        minimum_bounty=Amount(_get_int(policy, "minimum_bounty_atoms")),
        minimum_submission_bond=Amount(_get_int(policy, "minimum_submission_bond_atoms")),
        minimum_challenge_deposit=Amount(_get_int(policy, "minimum_challenge_deposit_atoms")),
        slashable_findings=frozenset(_get_str_tuple(policy, "slashable_findings")),
        treasury_ref=_get_str(policy, "treasury_ref"),
        challenge_resolution_seconds=_get_int(policy, "challenge_resolution_seconds"),
    )


# ---------------------------------------------------------------------------
# State hash computation.
# ---------------------------------------------------------------------------


def abstract_state_hash(state: SingleSlotAbstractState) -> str:
    return canonical_hash(STATE_HASH_DOMAIN, state.as_json())


# ---------------------------------------------------------------------------
# Time representative lookup.
# ---------------------------------------------------------------------------


def _time_class_to_epoch(profile: SingleSlotMarketProfileData, tc: TimeClassOrNone) -> int:
    if tc is TimeClassOrNone.NONE:
        return 0
    value = profile.time_representatives.get(tc.value)
    if type(value) is not int or isinstance(value, bool):
        raise ValueError(f"no time representative for {tc.value}")
    return value


def _epoch_to_time_class(profile: SingleSlotMarketProfileData, epoch: int) -> TimeClassOrNone:
    for tc in TimeClassOrNone:
        if tc is TimeClassOrNone.NONE:
            continue
        rep = profile.time_representatives.get(tc.value)
        if type(rep) is int and not isinstance(rep, bool) and rep == epoch:
            return tc
    raise ValueError(f"no time class matches epoch {epoch}")


# ---------------------------------------------------------------------------
# Projection: concrete BountyState → finite abstract state.
# ---------------------------------------------------------------------------


def project_state(profile: SingleSlotMarketProfileData, concrete: BountyState) -> SingleSlotAbstractState:
    """Project a concrete BountyState into the finite abstract state."""

    phase = AbstractPhase(concrete.phase.value)
    escrow = concrete.escrow_locked.atoms
    sub_status, bond, sub_tc = _project_submission(concrete, profile)
    ch_status, deposit, ch_tc = _project_challenge(concrete, profile)
    payable = bool(concrete.payable_submission_ids)
    settled = concrete.phase is BountyPhase.SETTLED
    mask = _project_processed_commands(concrete, profile)
    return SingleSlotAbstractState(
        phase=phase,
        escrow_atoms=escrow,
        submission_status=sub_status,
        submission_time_class=sub_tc,
        bond_atoms=bond,
        challenge_status=ch_status,
        challenge_opened_time_class=ch_tc,
        deposit_atoms=deposit,
        payable=payable,
        settled=settled,
        processed_command_mask=mask,
    )


def _project_submission(
    state: BountyState, profile: SingleSlotMarketProfileData,
) -> tuple[AbstractSubmissionStatus, int, TimeClassOrNone]:
    matching = [s for s in state.submissions if s.submission_id == profile.submission_id]
    if not matching:
        return (AbstractSubmissionStatus.NONE, 0, TimeClassOrNone.NONE)
    sub = matching[0]
    status_map = {
        SubmissionStatus.PENDING: AbstractSubmissionStatus.PENDING,
        SubmissionStatus.VERIFIED: AbstractSubmissionStatus.VERIFIED,
        SubmissionStatus.REJECTED: AbstractSubmissionStatus.REJECTED,
    }
    tc = _epoch_to_time_class(profile, sub.submitted_at)
    return (status_map[sub.status], sub.bond_locked.atoms, tc)


def _project_challenge(
    state: BountyState, profile: SingleSlotMarketProfileData,
) -> tuple[AbstractChallengeStatus, int, TimeClassOrNone]:
    matching = [c for c in state.challenges if c.challenge_id == profile.challenge_id]
    if not matching:
        return (AbstractChallengeStatus.NONE, 0, TimeClassOrNone.NONE)
    ch = matching[0]
    status_map = {
        ChallengeStatus.OPEN: AbstractChallengeStatus.OPEN,
        ChallengeStatus.UPHELD: AbstractChallengeStatus.UPHELD,
        ChallengeStatus.REJECTED: AbstractChallengeStatus.REJECTED,
    }
    tc = _epoch_to_time_class(profile, ch.opened_at)
    return (status_map[ch.status], ch.deposit_locked.atoms, tc)


def _project_processed_commands(state: BountyState, profile: SingleSlotMarketProfileData) -> int:
    mask = 0
    for slot in COMMAND_SLOTS:
        cmd_id = profile.command_ids.get(slot.value)
        if cmd_id is not None and cmd_id in state.processed_command_ids:
            mask |= 1 << COMMAND_SLOTS.index(slot)
    return mask


# ---------------------------------------------------------------------------
# Concretization: finite abstract state → concrete BountyState.
# ---------------------------------------------------------------------------


def concretize_state(profile: SingleSlotMarketProfileData, abstract: SingleSlotAbstractState) -> BountyState:
    """Concretize the finite abstract state into a valid PopperPad BountyState."""

    submissions = _concretize_submissions(profile, abstract)
    challenges = _concretize_challenges(profile, abstract)
    payable_ids = (profile.submission_id,) if abstract.payable else ()
    settlement_ref = profile.settlement_ref if abstract.settled else None
    processed = frozenset(
        profile.command_ids[slot.value]
        for slot in COMMAND_SLOTS
        if abstract.command_processed(slot) and slot.value in profile.command_ids
    )
    return BountyState(
        terms=profile.terms,
        phase=BountyPhase(abstract.phase.value),
        escrow_locked=Amount(abstract.escrow_atoms),
        submissions=submissions,
        challenges=challenges,
        payable_submission_ids=payable_ids,
        settlement_ref=settlement_ref,
        processed_command_ids=processed,
    )


def _concretize_submissions(
    profile: SingleSlotMarketProfileData, abstract: SingleSlotAbstractState,
) -> tuple[SubmissionState, ...]:
    if abstract.submission_status is AbstractSubmissionStatus.NONE:
        return ()
    status_map = {
        AbstractSubmissionStatus.PENDING: SubmissionStatus.PENDING,
        AbstractSubmissionStatus.VERIFIED: SubmissionStatus.VERIFIED,
        AbstractSubmissionStatus.REJECTED: SubmissionStatus.REJECTED,
    }
    receipt = profile.verifier_receipt_ref if abstract.submission_status in (
        AbstractSubmissionStatus.VERIFIED, AbstractSubmissionStatus.REJECTED,
    ) else None
    submitted_at = _time_class_to_epoch(profile, abstract.submission_time_class)
    return (
        SubmissionState(
            submission_id=profile.submission_id,
            submitter_ref=profile.submitter_ref,
            recipe_ref=profile.recipe_ref,
            verifier_ref=profile.verifier_ref,
            evidence_refs=profile.evidence_refs,
            artifact_refs=profile.artifact_refs,
            submitted_at=submitted_at,
            status=status_map[abstract.submission_status],
            bond_locked=Amount(abstract.bond_atoms),
            verifier_receipt_ref=receipt,
        ),
    )


def _concretize_challenges(
    profile: SingleSlotMarketProfileData, abstract: SingleSlotAbstractState,
) -> tuple[ChallengeState, ...]:
    if abstract.challenge_status is AbstractChallengeStatus.NONE:
        return ()
    status_map = {
        AbstractChallengeStatus.OPEN: ChallengeStatus.OPEN,
        AbstractChallengeStatus.UPHELD: ChallengeStatus.UPHELD,
        AbstractChallengeStatus.REJECTED: ChallengeStatus.REJECTED,
    }
    receipt = profile.challenge_receipt_ref if abstract.challenge_status in (
        AbstractChallengeStatus.UPHELD, AbstractChallengeStatus.REJECTED,
    ) else None
    opened_at = _time_class_to_epoch(profile, abstract.challenge_opened_time_class)
    return (
        ChallengeState(
            challenge_id=profile.challenge_id,
            submission_id=profile.submission_id,
            challenger_ref=profile.challenger_ref,
            finding_kind="invalid_signature",
            evidence_refs=profile.challenge_evidence_refs,
            opened_at=opened_at,
            status=status_map[abstract.challenge_status],
            deposit_locked=Amount(abstract.deposit_atoms),
            verifier_receipt_ref=receipt,
        ),
    )


# ---------------------------------------------------------------------------
# Concretize command: abstract command → concrete MarketCommand.
# ---------------------------------------------------------------------------


def concretize_command(
    profile: SingleSlotMarketProfileData,
    abstract: SingleSlotAbstractState,
    cmd: SingleSlotAbstractCommand,
    now_epoch_s: int,
    *,
    verifier_receipt_ref_override: str | None = None,
) -> MarketCommand:
    """Concretize an abstract command into a concrete MarketCommand.

    Time comes from the execution context (validated against profile).
    Command IDs come from the profile (fixed per slot).
    """

    cmd_id = profile.command_ids[cmd.kind.value]
    if cmd.kind is AbstractCommandKind.OPEN_BOUNTY:
        return OpenBounty(cmd_id, profile.sponsor_ref, Amount(profile.reward_atoms), now_epoch_s)
    if cmd.kind is AbstractCommandKind.SUBMIT_CANDIDATE:
        return SubmitCandidate(
            cmd_id, profile.submission_id, profile.submitter_ref, profile.recipe_ref,
            profile.verifier_ref, profile.evidence_refs, profile.artifact_refs,
            Amount(profile.bond_atoms), now_epoch_s,
        )
    if cmd.kind is AbstractCommandKind.VERIFY_SUBMISSION:
        return VerifySubmission(
            cmd_id, profile.submission_id, profile.verifier_ref,
            verifier_receipt_ref_override or profile.verifier_receipt_ref,
            cmd.accepted,
            now_epoch_s,
        )
    if cmd.kind is AbstractCommandKind.OPEN_CHALLENGE:
        return OpenChallenge(
            cmd_id, profile.challenge_id, profile.submission_id, profile.challenger_ref,
            "invalid_signature", profile.challenge_evidence_refs,
            Amount(profile.deposit_atoms), now_epoch_s,
        )
    if cmd.kind is AbstractCommandKind.RESOLVE_CHALLENGE:
        return ResolveChallenge(
            cmd_id, profile.challenge_id, profile.verifier_ref,
            verifier_receipt_ref_override or profile.challenge_receipt_ref,
            cmd.upheld,
            now_epoch_s,
        )
    if cmd.kind is AbstractCommandKind.ADVANCE_BOUNTY:
        return AdvanceBounty(cmd_id, now_epoch_s)
    if cmd.kind is AbstractCommandKind.SETTLE_BOUNTY:
        return SettleBounty(
            cmd_id, profile.settlement_ref,
            (Payout(profile.submitter_ref, profile.submission_id, Amount(profile.reward_atoms)),),
            now_epoch_s,
        )
    if cmd.kind is AbstractCommandKind.CANCEL_BOUNTY:
        return CancelBounty(cmd_id, profile.sponsor_ref, now_epoch_s)
    raise ValueError(f"unknown command kind: {cmd.kind}")


# ---------------------------------------------------------------------------
# The central adapter operation: apply_data_adapter.
# ---------------------------------------------------------------------------


def apply_data_adapter(
    profile: DataAdapterProfile,
    binding: AdapterBinding,
    request: AdapterRequest,
) -> AdapterResponse:
    """Apply one deterministic data-only adapter transition.

    Total over all properly constructed values. Expected boundary failures
    return INVALID_INPUT. Programming defects raise and terminate.
    """

    actual_profile_hash = profile.hash()
    if binding.profile_hash != actual_profile_hash:
        return _invalid_input(
            request,
            InvalidInputCode.PROFILE_MISMATCH,
            "$.binding_hash",
            f"binding profile_hash {binding.profile_hash} does not match loaded profile {actual_profile_hash}",
        )

    try:
        market = parse_market_profile(profile.semantic_profile)
    except (ValueError, TypeError, KeyError) as exc:
        return _invalid_input(
            request,
            InvalidInputCode.PROFILE_MISMATCH,
            "$.profile",
            f"bound semantic profile is invalid: {exc}",
        )

    # 1. Validate binding_hash matches
    if request.binding_hash != binding.hash():
        return _invalid_input(request, InvalidInputCode.BINDING_MISMATCH,
                              "$.binding_hash",
                              f"expected {binding.hash()}, got {request.binding_hash}")

    # 2. Parse abstract state
    try:
        abstract = SingleSlotAbstractState.from_json(request.state)
    except (ValueError, TypeError, KeyError) as exc:
        return _invalid_input(request, InvalidInputCode.ABSTRACT_STATE_OUT_OF_DOMAIN,
                              "$.state", str(exc))

    # 3. Enforce profile-bounded amounts
    try:
        validate_state_bounds(abstract, market.reward_atoms, market.bond_atoms, market.deposit_atoms)
    except ValueError as exc:
        return _invalid_input(request, InvalidInputCode.ABSTRACT_STATE_OUT_OF_DOMAIN,
                              "$.state", str(exc))

    # 4. Concretize state
    try:
        concrete_state = concretize_state(market, abstract)
    except (ValueError, TypeError, KeyError) as exc:
        return _invalid_input(request, InvalidInputCode.ABSTRACT_STATE_OUT_OF_DOMAIN,
                              "$.state", str(exc))

    # 5. Compute actual pre-state hash
    actual_pre_hash = abstract_state_hash(abstract)

    # 6. Enforce expected_pre_state_hash for BOTH operations
    if request.expected_pre_state_hash != actual_pre_hash:
        return _invalid_input(request, InvalidInputCode.PRE_STATE_HASH_MISMATCH,
                              "$.expected_pre_state_hash",
                              f"expected {actual_pre_hash}, got {request.expected_pre_state_hash}",
                              pre_state=abstract.as_json(), pre_state_hash=actual_pre_hash)

    if request.operation is AdapterOperation.VALIDATE_STATE:
        return _handle_validate_state(request, market, concrete_state, abstract, actual_pre_hash)

    return _handle_step(request, market, abstract, concrete_state, actual_pre_hash)


def _invalid_input(
    request: AdapterRequest,
    code: InvalidInputCode,
    field_path: str,
    detail: str,
    *,
    pre_state: FrozenDict[JsonValue] | None = None,
    pre_state_hash: str | None = None,
) -> AdapterResponse:
    return build_invalid_input_response(
        request=request,
        invalid=InvalidInput(code=code, field_path=field_path, detail=detail),
        pre_state=pre_state if pre_state is not None else FrozenDict(),
        pre_state_hash=pre_state_hash if pre_state_hash is not None else _ZERO_HASH,
    )


def _handle_validate_state(
    request: AdapterRequest,
    market: SingleSlotMarketProfileData,
    concrete_state: BountyState,
    abstract: SingleSlotAbstractState,
    actual_pre_hash: str,
) -> AdapterResponse:
    violations = market_state_violations(concrete_state)
    violation_json = tuple(v.as_json() for v in violations)
    if violations:
        return build_response(
            request=request,
            decision_kind=AdapterDecisionKind.REJECT,
            reason_code="INVALID_STATE",
            reason_details=FrozenDict({"violation_count": len(violations)}),
            pre_state=abstract.as_json(),
            pre_state_hash=actual_pre_hash,
            post_state=abstract.as_json(),
            post_state_hash=actual_pre_hash,
            effects=(),
            effect_plan_hash=None,
            receipt=None,
            state_violations=violation_json,
            projection_warnings=(),
        )
    validation_receipt = freeze_json(
        {
            "version": "popperpad/validation-receipt/v1",
            "request_id": request.request_id,
            "state_hash": actual_pre_hash,
            "violation_count": 0,
        }
    )
    assert isinstance(validation_receipt, FrozenDict)
    empty_eph = canonical_hash("popperpad-market-effects/v1", ())
    return build_response(
        request=request,
        decision_kind=AdapterDecisionKind.ACCEPT,
        reason_code=None,
        reason_details=FrozenDict({"violation_count": 0}),
        pre_state=abstract.as_json(),
        pre_state_hash=actual_pre_hash,
        post_state=abstract.as_json(),
        post_state_hash=actual_pre_hash,
        effects=(),
        effect_plan_hash=empty_eph,
        receipt=validation_receipt,
        state_violations=(),
        projection_warnings=(),
    )


def _handle_step(
    request: AdapterRequest,
    market: SingleSlotMarketProfileData,
    abstract: SingleSlotAbstractState,
    concrete_state: BountyState,
    actual_pre_hash: str,
) -> AdapterResponse:
    if request.command is None:
        return _invalid_input(request, InvalidInputCode.ABSTRACT_COMMAND_OUT_OF_DOMAIN,
                              "$.command", "STEP requires non-null command",
                              pre_state=abstract.as_json(), pre_state_hash=actual_pre_hash)

    try:
        cmd = SingleSlotAbstractCommand.from_json(request.command)
    except (ValueError, TypeError, KeyError) as exc:
        return _invalid_input(request, InvalidInputCode.ABSTRACT_COMMAND_OUT_OF_DOMAIN,
                              "$.command", str(exc),
                              pre_state=abstract.as_json(), pre_state_hash=actual_pre_hash)

    # Validate time class matches a declared representative
    now = request.execution_context.now_epoch_s
    expected_now = market.time_representatives.get(request.execution_context.time_class)
    if expected_now is None or expected_now != now:
        return _invalid_input(request, InvalidInputCode.ABSTRACT_STATE_OUT_OF_DOMAIN,
                              "$.execution_context",
                              f"time_class {request.execution_context.time_class} with now_epoch_s {now} does not match profile representative",
                              pre_state=abstract.as_json(), pre_state_hash=actual_pre_hash)

    try:
        evidence = _command_market_evidence(cmd)
        receipt_ref_override = (
            verifier_receipt_ref(evidence.verifier_receipts[0])
            if evidence.verifier_receipts
            else None
        )
        concrete_cmd = concretize_command(
            market,
            abstract,
            cmd,
            now,
            verifier_receipt_ref_override=receipt_ref_override,
        )
    except (ValueError, TypeError, KeyError) as exc:
        return _invalid_input(request, InvalidInputCode.ABSTRACT_COMMAND_OUT_OF_DOMAIN,
                              "$.command", str(exc),
                              pre_state=abstract.as_json(), pre_state_hash=actual_pre_hash)

    decision = apply_market_command(concrete_state, concrete_cmd, market.policy, evidence)

    if isinstance(decision, Reject):
        return build_response(
            request=request,
            decision_kind=AdapterDecisionKind.REJECT,
            reason_code=decision.code,
            reason_details=decision.details,
            pre_state=abstract.as_json(),
            pre_state_hash=actual_pre_hash,
            post_state=abstract.as_json(),
            post_state_hash=actual_pre_hash,
            effects=(),
            effect_plan_hash=None,
            receipt=None,
            state_violations=(),
            projection_warnings=(),
        )

    post_concrete = decision.next_state
    post_abstract = project_state(market, post_concrete)
    post_hash = abstract_state_hash(post_abstract)
    effect_json = tuple(e.as_json() for e in decision.effects)

    # Preserve the authoritative market receipt's effect_plan_hash verbatim.
    # Do NOT recompute under an adapter-specific domain.
    authoritative_eph = decision.receipt.effect_plan_hash

    receipt_json = freeze_json(
        {
            "version": decision.receipt.version,
            "bounty_id": decision.receipt.bounty_id,
            "command_id": decision.receipt.command_id,
            "event_kind": decision.receipt.event_kind,
            "occurred_at": decision.receipt.occurred_at,
            "previous_phase": decision.receipt.previous_phase.value,
            "next_phase": decision.receipt.next_phase.value,
            "command_hash": decision.receipt.command_hash,
            "state_hash": decision.receipt.state_hash,
            "effect_plan_hash": authoritative_eph,
        }
    )
    assert isinstance(receipt_json, FrozenDict)

    kind = AdapterDecisionKind.ACCEPT if isinstance(decision, Accept) else AdapterDecisionKind.COMMITTED_FAILURE
    reason_code = None if isinstance(decision, Accept) else decision.code
    reason_details = FrozenDict() if isinstance(decision, Accept) else decision.details

    return build_response(
        request=request,
        decision_kind=kind,
        reason_code=reason_code,
        reason_details=reason_details,
        pre_state=abstract.as_json(),
        pre_state_hash=actual_pre_hash,
        post_state=post_abstract.as_json(),
        post_state_hash=post_hash,
        effects=effect_json,
        effect_plan_hash=authoritative_eph,
        receipt=receipt_json,
        state_violations=(),
        projection_warnings=(),
    )


def _command_market_evidence(cmd: SingleSlotAbstractCommand) -> MarketEvidence:
    if cmd.verifier_receipt is None:
        return MarketEvidence()
    return MarketEvidence((_parse_verifier_receipt(cmd.verifier_receipt),))


def _parse_verifier_receipt(data: FrozenDict[JsonValue]) -> VerifierReceipt:
    _require_exact_object_fields(
        data,
        frozenset(
            {
                "schema",
                "algorithm",
                "public_key_hex",
                "signature_hex",
                "statement",
            }
        ),
        "verifier_receipt",
    )
    if _get_str(data, "schema") != "popperpad/market-verifier-receipt/v1":
        raise ValueError("verifier_receipt.schema is not supported")
    if _get_str(data, "algorithm") != "ed25519":
        raise ValueError("verifier_receipt.algorithm must be ed25519")
    return VerifierReceipt(
        statement=_parse_verifier_statement(_get_dict(data, "statement")),
        public_key=_decode_canonical_hex(data, "public_key_hex", byte_length=32),
        signature=_decode_canonical_hex(data, "signature_hex", byte_length=64),
    )


def _parse_verifier_statement(
    data: FrozenDict[JsonValue],
) -> SubmissionVerifierStatement | ChallengeVerifierStatement:
    schema = _get_str(data, "schema")
    if schema == "popperpad/market-verifier-statement/submission/v1":
        _require_exact_object_fields(
            data,
            frozenset(
                {
                    "schema",
                    "pre_state_hash",
                    "policy_hash",
                    "bounty_id",
                    "claim_ref",
                    "context_ref",
                    "submission_id",
                    "recipe_ref",
                    "evidence_refs",
                    "artifact_refs",
                    "outcome",
                }
            ),
            "verifier_receipt.statement",
        )
        return SubmissionVerifierStatement(
            pre_state_hash=_get_ref(data, "pre_state_hash"),
            policy_hash=_get_ref(data, "policy_hash"),
            bounty_id=_get_str(data, "bounty_id"),
            claim_ref=_get_ref(data, "claim_ref"),
            context_ref=_get_opt_ref(data, "context_ref"),
            submission_id=_get_str(data, "submission_id"),
            recipe_ref=_get_ref(data, "recipe_ref"),
            evidence_refs=_get_ref_tuple(data, "evidence_refs"),
            artifact_refs=_get_ref_tuple(data, "artifact_refs"),
            outcome=SubmissionVerdict(_get_str(data, "outcome")),
        )
    if schema == "popperpad/market-verifier-statement/challenge/v1":
        _require_exact_object_fields(
            data,
            frozenset(
                {
                    "schema",
                    "pre_state_hash",
                    "policy_hash",
                    "bounty_id",
                    "claim_ref",
                    "context_ref",
                    "challenge_id",
                    "submission_id",
                    "finding_kind",
                    "evidence_refs",
                    "outcome",
                }
            ),
            "verifier_receipt.statement",
        )
        return ChallengeVerifierStatement(
            pre_state_hash=_get_ref(data, "pre_state_hash"),
            policy_hash=_get_ref(data, "policy_hash"),
            bounty_id=_get_str(data, "bounty_id"),
            claim_ref=_get_ref(data, "claim_ref"),
            context_ref=_get_opt_ref(data, "context_ref"),
            challenge_id=_get_str(data, "challenge_id"),
            submission_id=_get_str(data, "submission_id"),
            finding_kind=_get_str(data, "finding_kind"),
            evidence_refs=_get_ref_tuple(data, "evidence_refs"),
            outcome=ChallengeVerdict(_get_str(data, "outcome")),
        )
    raise ValueError("verifier_receipt.statement.schema is not supported")


def _require_exact_object_fields(
    data: FrozenDict[JsonValue],
    expected: frozenset[str],
    field_path: str,
) -> None:
    actual = frozenset(data)
    unknown = sorted(actual - expected)
    if unknown:
        raise ValueError(f"{field_path} contains unknown fields: {unknown}")
    missing = sorted(expected - actual)
    if missing:
        raise ValueError(f"{field_path} is missing required fields: {missing}")


def _decode_canonical_hex(
    data: FrozenDict[JsonValue],
    key: str,
    *,
    byte_length: int,
) -> bytes:
    value = _get_str(data, key)
    if len(value) != byte_length * 2 or value != value.lower():
        raise ValueError(f"field {key!r} must be canonical lowercase hex")
    try:
        decoded = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"field {key!r} must be canonical lowercase hex") from exc
    if decoded.hex() != value:
        raise ValueError(f"field {key!r} must be canonical lowercase hex")
    return decoded

# ---------------------------------------------------------------------------
# JSON helper functions — strict, no silent normalization.
# ---------------------------------------------------------------------------


def _get_dict(d: FrozenDict[JsonValue], key: str) -> FrozenDict[JsonValue]:
    value = d.get(key)
    if not isinstance(value, FrozenDict):
        raise ValueError(f"field {key!r} must be an object, got {type(value).__name__}")
    return value


def _get_str(d: FrozenDict[JsonValue], key: str) -> str:
    value = d.get(key)
    if type(value) is not str:
        raise ValueError(f"field {key!r} must be a string, got {type(value).__name__}")
    return value


def _get_opt_str(d: FrozenDict[JsonValue], key: str) -> str | None:
    value = d.get(key)
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError(f"field {key!r} must be null or string")
    return value


def _get_int(d: FrozenDict[JsonValue], key: str) -> int:
    value = d.get(key)
    if type(value) is not int or isinstance(value, bool):
        raise ValueError(f"field {key!r} must be an integer, got {type(value).__name__}")
    return value


def _get_ref(d: FrozenDict[JsonValue], key: str) -> str:
    """Require a valid sha256 ref string — rejects non-strings and malformed refs."""

    value = d.get(key)
    if type(value) is not str:
        raise ValueError(f"field {key!r} must be a ref string, got {type(value).__name__}")
    if not _REF_RE.fullmatch(value):
        raise ValueError(f"field {key!r} is not a valid sha256 ref: {value!r}")
    return value


def _get_opt_ref(d: FrozenDict[JsonValue], key: str) -> str | None:
    value = d.get(key)
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError(f"field {key!r} must be null or a ref string")
    if not _REF_RE.fullmatch(value):
        raise ValueError(f"field {key!r} is not a valid sha256 ref: {value!r}")
    return value


def _get_ref_tuple(d: FrozenDict[JsonValue], key: str) -> tuple[str, ...]:
    """Require a tuple of valid sha256 ref strings — rejects malformed members."""

    value = d.get(key)
    if not isinstance(value, tuple):
        raise ValueError(f"field {key!r} must be an array, got {type(value).__name__}")
    result: list[str] = []
    for i, item in enumerate(value):
        if type(item) is not str:
            raise ValueError(f"field {key!r}[{i}] must be a string, got {type(item).__name__}")
        if not _REF_RE.fullmatch(item):
            raise ValueError(f"field {key!r}[{i}] is not a valid sha256 ref: {item!r}")
        result.append(item)
    return tuple(result)


def _get_str_tuple(d: FrozenDict[JsonValue], key: str) -> tuple[str, ...]:
    """Require a tuple of non-empty strings — rejects malformed members."""

    value = d.get(key)
    if not isinstance(value, tuple):
        raise ValueError(f"field {key!r} must be an array, got {type(value).__name__}")
    result: list[str] = []
    for i, item in enumerate(value):
        if type(item) is not str:
            raise ValueError(f"field {key!r}[{i}] must be a string, got {type(item).__name__}")
        if not item:
            raise ValueError(f"field {key!r}[{i}] must be a non-empty string")
        result.append(item)
    return tuple(result)
