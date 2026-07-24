"""Pure generic market projection — the abstraction relation.

This module implements the four pure operations that form the abstraction
relation between an ESSO finite-state model and the authoritative PopperPad
market core:

- ``project_state(profile, concrete_state)`` — concrete → abstract
- ``concretize_state(profile, abstract_state)`` — abstract → concrete
- ``concretize_command(profile, abstract_state, abstract_command, context)`` — abstract command → concrete command
- ``project_decision(profile, pre_abstract_state, runtime_decision)`` — concrete decision → abstract decision

It also provides ``apply_data_adapter(profile, request) -> AdapterResponse``,
the central adapter operation that is deterministic and total over all
properly constructed ``MarketAdapterProfile`` and ``AdapterRequest`` values.

Expected boundary failures are returned as data. Programming defects
terminate the process and grant no proof credit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from ..core.adapter_protocol import (
    ADAPTER_PROTOCOL_VERSION,
    ADAPTER_SCHEMA,
    InvalidInput,
    InvalidInputCode,
    MarketAdapterProfile,
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
    initial_bounty,
)
from ..core.market_invariants import market_state_violations
from ..core.result import Accept, CommittedFailure, Reject
from ..core.values import Amount, DeeplyImmutable, FrozenDict, JsonValue, freeze_json, thaw_json


# ---------------------------------------------------------------------------
# Hash domains for market abstract values (distinct from adapter protocol domains).
# ---------------------------------------------------------------------------

MARKET_ABSTRACT_STATE_DOMAIN = "popperpad-market-abstract-state/v1"
MARKET_ABSTRACT_COMMAND_DOMAIN = "popperpad-market-abstract-command/v1"
MARKET_ABSTRACTION_RELATION_DOMAIN = "popperpad-market-abstraction-relation/v1"


# ---------------------------------------------------------------------------
# Abstract state/command JSON shapes for the single-slot profile.
# ---------------------------------------------------------------------------

AbstractState: TypeAlias = FrozenDict[JsonValue]
AbstractCommand: TypeAlias = FrozenDict[JsonValue]


# ---------------------------------------------------------------------------
# Profile parsing — construct core types from profile JSON data.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ParsedProfile(DeeplyImmutable):
    """Parsed core values extracted from a MarketAdapterProfile's JSON fields.

    This is an internal value used by the projection functions. It is not
    part of the public adapter protocol.
    """

    terms: BountyTerms
    policy: MarketPolicy
    time_representatives: FrozenDict[JsonValue]
    identity_aliases: FrozenDict[JsonValue]


def _parse_profile(profile: MarketAdapterProfile) -> ParsedProfile:
    """Parse core BountyTerms and MarketPolicy from profile JSON data."""

    terms = _parse_bounty_terms(profile.bounty_terms_json, profile.identity_aliases)
    policy = _parse_market_policy(profile.market_policy_json)
    return ParsedProfile(
        terms=terms,
        policy=policy,
        time_representatives=profile.time_representatives,
        identity_aliases=profile.identity_aliases,
    )


def _parse_bounty_terms(
    terms_json: FrozenDict[JsonValue],
    identity_aliases: FrozenDict[JsonValue],
) -> BountyTerms:
    sponsor_ref = _str_from_aliases(identity_aliases, "sponsor")
    return BountyTerms(
        bounty_id=_req_str(terms_json, "bounty_id"),
        sponsor_ref=sponsor_ref,
        claim_ref=_req_str(terms_json, "claim_ref"),
        context_ref=_opt_str(terms_json, "context_ref"),
        reward=Amount(_req_int(terms_json, "reward_atoms")),
        minimum_submission_bond=Amount(_req_int(terms_json, "minimum_submission_bond_atoms")),
        deadline_epoch_s=_req_int(terms_json, "deadline_epoch_s"),
        challenge_window_seconds=_req_int(terms_json, "challenge_window_seconds"),
        accepted_recipe_refs=frozenset(_req_str_tuple(terms_json, "accepted_recipe_refs")),
        accepted_verifier_refs=frozenset(_req_str_tuple(terms_json, "accepted_verifier_refs")),
    )


def _parse_market_policy(policy_json: FrozenDict[JsonValue]) -> MarketPolicy:
    return MarketPolicy(
        minimum_bounty=Amount(_req_int(policy_json, "minimum_bounty_atoms")),
        minimum_submission_bond=Amount(_req_int(policy_json, "minimum_submission_bond_atoms")),
        minimum_challenge_deposit=Amount(_req_int(policy_json, "minimum_challenge_deposit_atoms")),
        slashable_findings=frozenset(_req_str_tuple(policy_json, "slashable_findings")),
        treasury_ref=_req_str(policy_json, "treasury_ref"),
        challenge_resolution_seconds=_req_int(policy_json, "challenge_resolution_seconds"),
    )


# ---------------------------------------------------------------------------
# Projection: concrete BountyState → abstract state JSON.
# ---------------------------------------------------------------------------


def project_state(profile: MarketAdapterProfile, concrete_state: BountyState) -> AbstractState:
    """Project a concrete BountyState into the abstract state representation."""

    state_json = _state_to_json(concrete_state)
    return state_json


def _state_to_json(state: BountyState) -> FrozenDict[JsonValue]:
    value = freeze_json(
        {
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
                    "submission_id": sub.submission_id,
                    "submitter_ref": sub.submitter_ref,
                    "recipe_ref": sub.recipe_ref,
                    "verifier_ref": sub.verifier_ref,
                    "evidence_refs": sub.evidence_refs,
                    "artifact_refs": sub.artifact_refs,
                    "submitted_at": sub.submitted_at,
                    "status": sub.status.value,
                    "bond_locked_atoms": sub.bond_locked.atoms,
                    "verifier_receipt_ref": sub.verifier_receipt_ref,
                }
                for sub in state.submissions
            ),
            "challenges": tuple(
                {
                    "challenge_id": ch.challenge_id,
                    "submission_id": ch.submission_id,
                    "challenger_ref": ch.challenger_ref,
                    "finding_kind": ch.finding_kind,
                    "evidence_refs": ch.evidence_refs,
                    "opened_at": ch.opened_at,
                    "status": ch.status.value,
                    "deposit_locked_atoms": ch.deposit_locked.atoms,
                    "verifier_receipt_ref": ch.verifier_receipt_ref,
                }
                for ch in state.challenges
            ),
            "payable_submission_ids": state.payable_submission_ids,
            "settlement_ref": state.settlement_ref,
            "processed_command_ids": tuple(sorted(state.processed_command_ids)),
        }
    )
    assert isinstance(value, FrozenDict)
    return value


# ---------------------------------------------------------------------------
# Concretization: abstract state JSON → concrete BountyState.
# ---------------------------------------------------------------------------


def concretize_state(profile: MarketAdapterProfile, abstract_state: AbstractState) -> BountyState:
    """Concretize an abstract state into a valid PopperPad BountyState."""

    parsed = _parse_profile(profile)
    terms = parsed.terms
    phase = BountyPhase(_req_str(abstract_state, "phase"))
    escrow = Amount(_req_int(abstract_state, "escrow_locked_atoms"))
    submissions = _parse_submissions(abstract_state)
    challenges = _parse_challenges(abstract_state)
    payable_ids = _req_str_tuple(abstract_state, "payable_submission_ids")
    settlement_ref = _opt_str(abstract_state, "settlement_ref")
    processed = frozenset(_req_str_tuple(abstract_state, "processed_command_ids"))
    return BountyState(
        terms=terms,
        phase=phase,
        escrow_locked=escrow,
        submissions=submissions,
        challenges=challenges,
        payable_submission_ids=payable_ids,
        settlement_ref=settlement_ref,
        processed_command_ids=processed,
    )


def _parse_submissions(state_json: FrozenDict[JsonValue]) -> tuple[SubmissionState, ...]:
    raw = state_json.get("submissions")
    if not isinstance(raw, tuple):
        return ()
    return tuple(_parse_submission(item) for item in raw if isinstance(item, FrozenDict))


def _parse_submission(item: FrozenDict[JsonValue]) -> SubmissionState:
    return SubmissionState(
        submission_id=_req_str(item, "submission_id"),
        submitter_ref=_req_str(item, "submitter_ref"),
        recipe_ref=_req_str(item, "recipe_ref"),
        verifier_ref=_req_str(item, "verifier_ref"),
        evidence_refs=_req_str_tuple(item, "evidence_refs"),
        artifact_refs=_req_str_tuple(item, "artifact_refs"),
        submitted_at=_req_int(item, "submitted_at"),
        status=SubmissionStatus(_req_str(item, "status")),
        bond_locked=Amount(_req_int(item, "bond_locked_atoms")),
        verifier_receipt_ref=_opt_str(item, "verifier_receipt_ref"),
    )


def _parse_challenges(state_json: FrozenDict[JsonValue]) -> tuple[ChallengeState, ...]:
    raw = state_json.get("challenges")
    if not isinstance(raw, tuple):
        return ()
    return tuple(_parse_challenge(item) for item in raw if isinstance(item, FrozenDict))


def _parse_challenge(item: FrozenDict[JsonValue]) -> ChallengeState:
    return ChallengeState(
        challenge_id=_req_str(item, "challenge_id"),
        submission_id=_req_str(item, "submission_id"),
        challenger_ref=_req_str(item, "challenger_ref"),
        finding_kind=_req_str(item, "finding_kind"),
        evidence_refs=_req_str_tuple(item, "evidence_refs"),
        opened_at=_req_int(item, "opened_at"),
        status=ChallengeStatus(_req_str(item, "status")),
        deposit_locked=Amount(_req_int(item, "deposit_locked_atoms")),
        verifier_receipt_ref=_opt_str(item, "verifier_receipt_ref"),
    )


# ---------------------------------------------------------------------------
# Concretize command: abstract command JSON → concrete MarketCommand.
# ---------------------------------------------------------------------------


def concretize_command(
    profile: MarketAdapterProfile,
    abstract_state: AbstractState,
    abstract_command: AbstractCommand,
    context: ExecutionContext,
) -> MarketCommand:
    """Concretize an abstract command into an actual PopperPad MarketCommand.

    Time comes from the execution context, not from synthetic commands.
    The abstract command ``kind`` field selects the concrete command variant.
    """

    kind = _req_str(abstract_command, "kind")
    now = context.now_epoch_s
    aliases = profile.identity_aliases
    if kind == "open_bounty":
        return OpenBounty(
            command_id=_req_str(abstract_command, "command_id"),
            sponsor_ref=_str_from_aliases(aliases, "sponsor"),
            funded=Amount(_req_int(abstract_command, "funded_atoms")),
            now_epoch_s=now,
        )
    if kind == "submit_candidate":
        return SubmitCandidate(
            command_id=_req_str(abstract_command, "command_id"),
            submission_id=_req_str(abstract_command, "submission_id"),
            submitter_ref=_str_from_aliases(aliases, "submitter"),
            recipe_ref=_str_from_aliases(aliases, "recipe"),
            verifier_ref=_str_from_aliases(aliases, "verifier"),
            evidence_refs=_str_tuple_from_aliases(aliases, "evidence_refs"),
            artifact_refs=_str_tuple_from_aliases(aliases, "artifact_refs"),
            bond=Amount(_req_int(abstract_command, "bond_atoms")),
            now_epoch_s=now,
        )
    if kind == "verify_submission":
        return VerifySubmission(
            command_id=_req_str(abstract_command, "command_id"),
            submission_id=_req_str(abstract_command, "submission_id"),
            verifier_ref=_str_from_aliases(aliases, "verifier"),
            verifier_receipt_ref=_str_from_aliases(aliases, "verifier_receipt"),
            accepted=_req_bool(abstract_command, "accepted"),
            now_epoch_s=now,
        )
    if kind == "open_challenge":
        return OpenChallenge(
            command_id=_req_str(abstract_command, "command_id"),
            challenge_id=_req_str(abstract_command, "challenge_id"),
            submission_id=_req_str(abstract_command, "submission_id"),
            challenger_ref=_str_from_aliases(aliases, "challenger"),
            finding_kind=_req_str(abstract_command, "finding_kind"),
            evidence_refs=_str_tuple_from_aliases(aliases, "challenge_evidence_refs"),
            deposit=Amount(_req_int(abstract_command, "deposit_atoms")),
            now_epoch_s=now,
        )
    if kind == "resolve_challenge":
        return ResolveChallenge(
            command_id=_req_str(abstract_command, "command_id"),
            challenge_id=_req_str(abstract_command, "challenge_id"),
            verifier_ref=_str_from_aliases(aliases, "verifier"),
            verifier_receipt_ref=_str_from_aliases(aliases, "challenge_receipt"),
            upheld=_req_bool(abstract_command, "upheld"),
            now_epoch_s=now,
        )
    if kind == "advance_bounty":
        return AdvanceBounty(
            command_id=_req_str(abstract_command, "command_id"),
            now_epoch_s=now,
        )
    if kind == "settle_bounty":
        return SettleBounty(
            command_id=_req_str(abstract_command, "command_id"),
            settlement_ref=_str_from_aliases(aliases, "settlement"),
            payouts=_parse_payouts(abstract_command),
            now_epoch_s=now,
        )
    if kind == "cancel_bounty":
        return CancelBounty(
            command_id=_req_str(abstract_command, "command_id"),
            sponsor_ref=_str_from_aliases(aliases, "sponsor"),
            now_epoch_s=now,
        )
    raise ValueError(f"unknown command kind: {kind}")


def _parse_payouts(abstract_command: AbstractCommand) -> tuple[Payout, ...]:
    raw = abstract_command.get("payouts")
    if not isinstance(raw, tuple):
        return ()
    return tuple(
        Payout(
            recipient_ref=_req_str(item, "recipient_ref"),
            submission_id=_req_str(item, "submission_id"),
            amount=Amount(_req_int(item, "amount_atoms")),
        )
        for item in raw
        if isinstance(item, FrozenDict)
    )


# ---------------------------------------------------------------------------
# Project decision: concrete MarketDecision → abstract decision data.
# ---------------------------------------------------------------------------


def project_decision(
    profile: MarketAdapterProfile,
    pre_abstract_state: AbstractState,
    runtime_decision: Reject | Accept[BountyState, MarketEffect, object] | CommittedFailure[BountyState, MarketEffect, object],
) -> tuple[AdapterDecisionKind, str | None, FrozenDict[JsonValue], BountyState | None, tuple[MarketEffect, ...], object | None]:
    """Project a concrete runtime decision into abstract decision data.

    Returns (decision_kind, reason_code, reason_details, post_state, effects, receipt).
    """

    if isinstance(runtime_decision, Reject):
        return (AdapterDecisionKind.REJECT, runtime_decision.code, runtime_decision.details, None, (), None)
    if isinstance(runtime_decision, Accept):
        return (AdapterDecisionKind.ACCEPT, None, FrozenDict(), runtime_decision.next_state, runtime_decision.effects, runtime_decision.receipt)
    if isinstance(runtime_decision, CommittedFailure):
        return (AdapterDecisionKind.COMMITTED_FAILURE, runtime_decision.code, runtime_decision.details, runtime_decision.next_state, runtime_decision.effects, runtime_decision.receipt)
    raise TypeError(f"unknown decision type: {type(runtime_decision).__name__}")


# ---------------------------------------------------------------------------
# Effect and receipt projection.
# ---------------------------------------------------------------------------


def _effect_to_json(effect: MarketEffect) -> FrozenDict[JsonValue]:
    return effect.as_json()


def _receipt_to_json(receipt: object) -> FrozenDict[JsonValue]:
    from ..core.market import TransitionReceipt

    if not isinstance(receipt, TransitionReceipt):
        raise TypeError("receipt must be a TransitionReceipt")
    value = freeze_json(
        {
            "version": receipt.version,
            "bounty_id": receipt.bounty_id,
            "command_id": receipt.command_id,
            "event_kind": receipt.event_kind,
            "occurred_at": receipt.occurred_at,
            "previous_phase": receipt.previous_phase.value,
            "next_phase": receipt.next_phase.value,
            "command_hash": receipt.command_hash,
            "state_hash": receipt.state_hash,
            "effect_plan_hash": receipt.effect_plan_hash,
        }
    )
    assert isinstance(value, FrozenDict)
    return value


# ---------------------------------------------------------------------------
# State hash computation.
# ---------------------------------------------------------------------------


def _state_hash(state: BountyState) -> str:
    return canonical_hash("market-state/v1", _state_to_json(state))


def _effect_plan_hash(effects: tuple[MarketEffect, ...]) -> str:
    return canonical_hash("market-effects/v1", tuple(_effect_to_json(e) for e in effects))


# ---------------------------------------------------------------------------
# Violation projection.
# ---------------------------------------------------------------------------


def _violations_to_json(violations: tuple[object, ...]) -> tuple[FrozenDict[JsonValue], ...]:
    from ..core.market_invariants import MarketStateViolation

    return tuple(
        v.as_json() for v in violations if isinstance(v, MarketStateViolation)
    )


# ---------------------------------------------------------------------------
# The central adapter operation: apply_data_adapter.
# ---------------------------------------------------------------------------


def apply_data_adapter(
    profile: MarketAdapterProfile,
    request: AdapterRequest,
) -> AdapterResponse:
    """Apply one deterministic data-only adapter transition.

    This function is total over all properly constructed profile and request
    values. Expected boundary failures are returned as data (INVALID_INPUT).
    Programming defects raise and terminate the process.
    """

    parsed = _parse_profile(profile)
    pre_state_hash = request.expected_pre_state_hash

    if request.operation is AdapterOperation.VALIDATE_STATE:
        return _handle_validate_state(profile, request, parsed, pre_state_hash)

    return _handle_step(profile, request, parsed, pre_state_hash)


def _handle_validate_state(
    profile: MarketAdapterProfile,
    request: AdapterRequest,
    parsed: ParsedProfile,
    pre_state_hash: str,
) -> AdapterResponse:
    try:
        concrete_state = concretize_state(profile, request.state)
    except (ValueError, TypeError, KeyError) as exc:
        return _invalid_input(
            profile, request, InvalidInputCode.ABSTRACT_STATE_OUT_OF_DOMAIN,
            "$.state", str(exc), request.state, pre_state_hash,
        )
    violations = market_state_violations(concrete_state)
    violation_json = _violations_to_json(violations)
    abstract_state = project_state(profile, concrete_state)
    actual_hash = _state_hash(concrete_state)
    if violations:
        return build_response(
            request=request,
            profile=profile,
            decision_kind=AdapterDecisionKind.REJECT,
            reason_code="INVALID_STATE",
            reason_details=FrozenDict({"violation_count": len(violations)}),
            pre_state=abstract_state,
            pre_state_hash=actual_hash,
            post_state=abstract_state,
            post_state_hash=actual_hash,
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
            "state_hash": actual_hash,
            "violation_count": 0,
        }
    )
    assert isinstance(validation_receipt, FrozenDict)
    return build_response(
        request=request,
        profile=profile,
        decision_kind=AdapterDecisionKind.ACCEPT,
        reason_code=None,
        reason_details=FrozenDict({"violation_count": 0}),
        pre_state=abstract_state,
        pre_state_hash=actual_hash,
        post_state=abstract_state,
        post_state_hash=actual_hash,
        effects=(),
        effect_plan_hash=canonical_hash("market-effects/v1", ()),
        receipt=validation_receipt,
        state_violations=(),
        projection_warnings=(),
    )


def _handle_step(
    profile: MarketAdapterProfile,
    request: AdapterRequest,
    parsed: ParsedProfile,
    pre_state_hash: str,
) -> AdapterResponse:
    try:
        concrete_state = concretize_state(profile, request.state)
    except (ValueError, TypeError, KeyError) as exc:
        return _invalid_input(
            profile, request, InvalidInputCode.ABSTRACT_STATE_OUT_OF_DOMAIN,
            "$.state", str(exc), request.state, pre_state_hash,
        )
    if request.command is None:
        return _invalid_input(
            profile, request, InvalidInputCode.ABSTRACT_COMMAND_OUT_OF_DOMAIN,
            "$.command", "STEP requires non-null command", request.state, pre_state_hash,
        )
    try:
        concrete_command = concretize_command(profile, request.state, request.command, request.execution_context)
    except (ValueError, TypeError, KeyError) as exc:
        return _invalid_input(
            profile, request, InvalidInputCode.ABSTRACT_COMMAND_OUT_OF_DOMAIN,
            "$.command", str(exc), request.state, pre_state_hash,
        )
    pre_abstract = project_state(profile, concrete_state)
    actual_pre_hash = _state_hash(concrete_state)
    decision = apply_market_command(concrete_state, concrete_command, parsed.policy)
    kind, reason_code, reason_details, post_state, effects, receipt = project_decision(
        profile, pre_abstract, decision,
    )
    if kind is AdapterDecisionKind.REJECT:
        return build_response(
            request=request,
            profile=profile,
            decision_kind=kind,
            reason_code=reason_code,
            reason_details=reason_details,
            pre_state=pre_abstract,
            pre_state_hash=actual_pre_hash,
            post_state=pre_abstract,
            post_state_hash=actual_pre_hash,
            effects=(),
            effect_plan_hash=None,
            receipt=None,
            state_violations=(),
            projection_warnings=(),
        )
    if post_state is None or receipt is None:
        raise AssertionError("non-REJECT decision must have post_state and receipt")
    post_abstract = project_state(profile, post_state)
    post_hash = _state_hash(post_state)
    effect_json = tuple(_effect_to_json(e) for e in effects)
    eph = _effect_plan_hash(effects)
    receipt_json = _receipt_to_json(receipt)
    violations = market_state_violations(post_state)
    violation_json = _violations_to_json(violations)
    return build_response(
        request=request,
        profile=profile,
        decision_kind=kind,
        reason_code=reason_code,
        reason_details=reason_details,
        pre_state=pre_abstract,
        pre_state_hash=actual_pre_hash,
        post_state=post_abstract,
        post_state_hash=post_hash,
        effects=effect_json,
        effect_plan_hash=eph,
        receipt=receipt_json,
        state_violations=violation_json,
        projection_warnings=(),
    )


def _invalid_input(
    profile: MarketAdapterProfile,
    request: AdapterRequest,
    code: InvalidInputCode,
    field_path: str,
    detail: str,
    pre_state: FrozenDict[JsonValue],
    pre_state_hash: str,
) -> AdapterResponse:
    invalid = InvalidInput(code=code, field_path=field_path, detail=detail)
    return build_invalid_input_response(
        request=request,
        profile=profile,
        invalid=invalid,
        pre_state=pre_state,
        pre_state_hash=pre_state_hash,
    )


# ---------------------------------------------------------------------------
# JSON helper functions.
# ---------------------------------------------------------------------------


def _req_str(d: FrozenDict[JsonValue], key: str) -> str:
    value = d.get(key)
    if type(value) is not str:
        raise ValueError(f"field {key!r} must be a string, got {type(value).__name__}")
    return value


def _opt_str(d: FrozenDict[JsonValue], key: str) -> str | None:
    value = d.get(key)
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError(f"field {key!r} must be null or string, got {type(value).__name__}")
    return value


def _req_int(d: FrozenDict[JsonValue], key: str) -> int:
    value = d.get(key)
    if type(value) is not int or isinstance(value, bool):
        raise ValueError(f"field {key!r} must be an integer, got {type(value).__name__}")
    return value


def _req_bool(d: FrozenDict[JsonValue], key: str) -> bool:
    value = d.get(key)
    if type(value) is not bool:
        raise ValueError(f"field {key!r} must be a boolean, got {type(value).__name__}")
    return value


def _req_str_tuple(d: FrozenDict[JsonValue], key: str) -> tuple[str, ...]:
    value = d.get(key)
    if not isinstance(value, tuple):
        raise ValueError(f"field {key!r} must be a tuple, got {type(value).__name__}")
    return tuple(_check_str(item, key) for item in value)


def _check_str(value: object, context: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{context} must contain strings, got {type(value).__name__}")
    return value


def _str_from_aliases(aliases: FrozenDict[JsonValue], key: str) -> str:
    value = aliases.get(key)
    if type(value) is not str:
        raise ValueError(f"identity alias {key!r} must be a string, got {type(value).__name__}")
    return value


def _str_tuple_from_aliases(aliases: FrozenDict[JsonValue], key: str) -> tuple[str, ...]:
    value = aliases.get(key)
    if not isinstance(value, tuple):
        raise ValueError(f"identity alias {key!r} must be a tuple, got {type(value).__name__}")
    return tuple(_check_str(item, key) for item in value)
