"""Tests for the bounded falsification-market adapter (PR A2).

Tests verify:
- Architecture: adapter imports core, not vice versa; finite state is closed.
- Abstraction relation: representability, projection stability.
- Pre-state hash enforcement (both STEP and VALIDATE_STATE).
- Binding hash enforcement.
- Time class enforcement.
- Profile-bounded amount enforcement (defect 1).
- Time-class preservation in abstract state (defect 2).
- Malformed array member rejection in profile parsing (defect 3).
- Variant-inapplicable field rejection in commands (defect 4).
- Authoritative effect_plan_hash preservation (defect 7).
- Transition parity: open_bounty, full lifecycle, committed failure.
- Finite state: no arbitrary IDs/refs/timestamps in abstract state.
- Complete BFS enumeration: search_complete, budget not exhausted.
- Source manifest and binding hash verification at load time (defect 9).
"""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest

from popperpad.core.adapter_protocol import (
    ADAPTER_PROTOCOL_VERSION,
    BINDING_SCHEMA,
    REQUEST_SCHEMA,
    AdapterBinding,
    AdapterDecisionKind,
    AdapterOperation,
    AdapterRequest,
    ExecutionContext,
    InvalidInputCode,
    SOURCE_MANIFEST_SCHEMA,
    SourceFileBinding,
    SourceManifest,
)
from popperpad.core.codec import sha256_bytes
from popperpad.core.market_invariants import market_state_violations, MarketStateViolationCode
from popperpad.core.values import FrozenDict, freeze_json, thaw_json
from popperpad.refinement.finite_state import (
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
from popperpad.refinement.market_adapter import (
    apply_data_adapter,
    concretize_state,
    project_state,
    parse_market_profile,
    abstract_state_hash,
)
from popperpad.refinement.profiles.market_single_slot_v1 import (
    load_profile,
    load_binding,
    load_source_manifest,
    verify_source_manifest_files,
)


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------

@pytest.fixture
def profile():
    return load_profile()


@pytest.fixture
def binding(profile):
    return load_binding(profile)


@pytest.fixture
def market(profile):
    return parse_market_profile(profile.semantic_profile)


def _make_request(
    binding,
    state,
    command=None,
    operation=AdapterOperation.STEP,
    time_class="pre_deadline",
    now_epoch_s=100,
    request_id="req-1",
    expected_pre_state_hash=None,
):
    return AdapterRequest(
        schema=REQUEST_SCHEMA,
        protocol_version=ADAPTER_PROTOCOL_VERSION,
        request_id=request_id,
        case_id="case-1",
        binding_hash=binding.hash(),
        operation=operation,
        state=state,
        command=command,
        execution_context=ExecutionContext(time_class=time_class, now_epoch_s=now_epoch_s),
        expected_pre_state_hash=expected_pre_state_hash or abstract_state_hash(
            SingleSlotAbstractState.from_json(state)
        ),
    )


# ---------------------------------------------------------------------------
# Architecture tests.
# ---------------------------------------------------------------------------

_FORBIDDEN_IMPORT_ROOTS = {
    "asyncio", "datetime", "multiprocessing", "os", "pathlib",
    "random", "requests", "socket", "sqlite3", "subprocess",
    "tempfile", "threading", "time", "urllib", "web3",
}


def test_market_adapter_has_no_forbidden_imports() -> None:
    path = Path(__import__("popperpad.refinement.market_adapter", fromlist=["__file__"]).__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        for name in names:
            root = name.split(".", 1)[0]
            assert root not in _FORBIDDEN_IMPORT_ROOTS, name


def test_core_does_not_import_refinement_or_shells() -> None:
    from popperpad.core import market

    path = Path(market.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "refinement" not in node.module, node.module
            assert "shells" not in node.module, node.module


# ---------------------------------------------------------------------------
# Finite abstract state tests.
# ---------------------------------------------------------------------------

def test_abstract_state_has_no_arbitrary_ids() -> None:
    state = initial_abstract_state()
    json_data = state.as_json()
    assert "submission_id" not in json_data
    assert "challenge_id" not in json_data
    assert "submitter_ref" not in json_data
    assert "evidence_refs" not in json_data


def test_abstract_state_is_finite_and_closed() -> None:
    state = initial_abstract_state()
    assert state.phase in AbstractPhase
    assert state.submission_status in AbstractSubmissionStatus
    assert state.challenge_status in AbstractChallengeStatus
    assert state.submission_time_class in TimeClassOrNone
    assert state.challenge_opened_time_class in TimeClassOrNone
    assert 0 <= state.processed_command_mask < (1 << len(COMMAND_SLOTS))


def test_initial_state_is_draft_with_no_activity() -> None:
    state = initial_abstract_state()
    assert state.phase is AbstractPhase.DRAFT
    assert state.escrow_atoms == 0
    assert state.submission_status is AbstractSubmissionStatus.NONE
    assert state.submission_time_class is TimeClassOrNone.NONE
    assert state.challenge_status is AbstractChallengeStatus.NONE
    assert state.challenge_opened_time_class is TimeClassOrNone.NONE
    assert state.payable is False
    assert state.settled is False
    assert state.processed_command_mask == 0


# ---------------------------------------------------------------------------
# Defect 1: Profile-bounded amount enforcement.
# ---------------------------------------------------------------------------

def test_state_bounds_reject_escrow_exceeding_reward() -> None:
    state = SingleSlotAbstractState(
        phase=AbstractPhase.OPEN,
        escrow_atoms=9999,
        submission_status=AbstractSubmissionStatus.NONE,
        submission_time_class=TimeClassOrNone.NONE,
        bond_atoms=0,
        challenge_status=AbstractChallengeStatus.NONE,
        challenge_opened_time_class=TimeClassOrNone.NONE,
        deposit_atoms=0,
        payable=False,
        settled=False,
        processed_command_mask=0,
    )
    with pytest.raises(ValueError, match="escrow_atoms"):
        validate_state_bounds(state, reward_atoms=1000, bond_atoms=100, deposit_atoms=50)


def test_state_bounds_reject_bond_exceeding_profile() -> None:
    state = SingleSlotAbstractState(
        phase=AbstractPhase.OPEN,
        escrow_atoms=1000,
        submission_status=AbstractSubmissionStatus.PENDING,
        submission_time_class=TimeClassOrNone.PRE_DEADLINE,
        bond_atoms=9999,
        challenge_status=AbstractChallengeStatus.NONE,
        challenge_opened_time_class=TimeClassOrNone.NONE,
        deposit_atoms=0,
        payable=False,
        settled=False,
        processed_command_mask=0,
    )
    with pytest.raises(ValueError, match="bond_atoms"):
        validate_state_bounds(state, reward_atoms=1000, bond_atoms=100, deposit_atoms=50)


def test_state_bounds_reject_deposit_exceeding_profile() -> None:
    state = SingleSlotAbstractState(
        phase=AbstractPhase.OPEN,
        escrow_atoms=1000,
        submission_status=AbstractSubmissionStatus.VERIFIED,
        submission_time_class=TimeClassOrNone.PRE_DEADLINE,
        bond_atoms=0,
        challenge_status=AbstractChallengeStatus.OPEN,
        challenge_opened_time_class=TimeClassOrNone.CHALLENGE_WINDOW,
        deposit_atoms=9999,
        payable=False,
        settled=False,
        processed_command_mask=0,
    )
    with pytest.raises(ValueError, match="deposit_atoms"):
        validate_state_bounds(state, reward_atoms=1000, bond_atoms=100, deposit_atoms=50)


def test_adapter_rejects_state_with_unbounded_escrow(binding) -> None:
    bad_state = freeze_json({
        "phase": "open", "escrow_atoms": 9999,
        "submission_status": "none", "submission_time_class": "none",
        "bond_atoms": 0,
        "challenge_status": "none", "challenge_opened_time_class": "none",
        "deposit_atoms": 0, "payable": False, "settled": False,
        "processed_command_mask": 0,
    })
    req = _make_request(binding, bad_state, None, operation=AdapterOperation.VALIDATE_STATE,
                        expected_pre_state_hash="sha256:" + "0" * 64)
    resp = apply_data_adapter(load_profile(), binding, req)
    assert resp.decision_kind is AdapterDecisionKind.INVALID_INPUT


# ---------------------------------------------------------------------------
# Defect 2: Time-class preservation.
# ---------------------------------------------------------------------------

def test_state_preserves_submission_time_class() -> None:
    state = SingleSlotAbstractState(
        phase=AbstractPhase.OPEN,
        escrow_atoms=1000,
        submission_status=AbstractSubmissionStatus.PENDING,
        submission_time_class=TimeClassOrNone.PRE_DEADLINE,
        bond_atoms=100,
        challenge_status=AbstractChallengeStatus.NONE,
        challenge_opened_time_class=TimeClassOrNone.NONE,
        deposit_atoms=0,
        payable=False,
        settled=False,
        processed_command_mask=0,
    )
    assert state.submission_time_class is TimeClassOrNone.PRE_DEADLINE


def test_state_preserves_challenge_opened_time_class() -> None:
    state = SingleSlotAbstractState(
        phase=AbstractPhase.OPEN,
        escrow_atoms=1000,
        submission_status=AbstractSubmissionStatus.VERIFIED,
        submission_time_class=TimeClassOrNone.PRE_DEADLINE,
        bond_atoms=0,
        challenge_status=AbstractChallengeStatus.OPEN,
        challenge_opened_time_class=TimeClassOrNone.CHALLENGE_WINDOW,
        deposit_atoms=50,
        payable=False,
        settled=False,
        processed_command_mask=0,
    )
    assert state.challenge_opened_time_class is TimeClassOrNone.CHALLENGE_WINDOW


def test_state_rejects_time_class_mismatch_with_existence() -> None:
    with pytest.raises(ValueError, match="submission_time_class must be none"):
        SingleSlotAbstractState(
            phase=AbstractPhase.DRAFT,
            escrow_atoms=0,
            submission_status=AbstractSubmissionStatus.NONE,
            submission_time_class=TimeClassOrNone.PRE_DEADLINE,  # Wrong: none should be NONE
            bond_atoms=0,
            challenge_status=AbstractChallengeStatus.NONE,
            challenge_opened_time_class=TimeClassOrNone.NONE,
            deposit_atoms=0,
            payable=False,
            settled=False,
            processed_command_mask=0,
        )


# ---------------------------------------------------------------------------
# Defect 3: Malformed array member rejection.
# ---------------------------------------------------------------------------

def test_profile_parsing_rejects_malformed_ref_in_array() -> None:
    bad_semantic = freeze_json({
        "bounty_terms": {
            "bounty_id": "bounty-1",
            "sponsor_ref": "did:example:sponsor",
            "claim_ref": "sha256:" + "a" * 64,
            "context_ref": None,
            "reward_atoms": 1000,
            "minimum_submission_bond_atoms": 100,
            "deadline_epoch_s": 1000,
            "challenge_window_seconds": 100,
            "accepted_recipe_refs": ["sha256:" + "c" * 64, 7],  # Malformed: int member
            "accepted_verifier_refs": ["sha256:" + "d" * 64],
        },
        "market_policy": {
            "minimum_bounty_atoms": 1000,
            "minimum_submission_bond_atoms": 100,
            "minimum_challenge_deposit_atoms": 50,
            "slashable_findings": ["invalid_signature"],
            "treasury_ref": "protocol:treasury",
            "challenge_resolution_seconds": 100,
        },
        "identities": {
            "submission_id": "submission-1",
            "challenge_id": "challenge-1",
            "sponsor_ref": "did:example:sponsor",
            "submitter_ref": "did:example:refuter",
            "challenger_ref": "did:example:challenger",
            "recipe_ref": "sha256:" + "c" * 64,
            "verifier_ref": "sha256:" + "d" * 64,
            "evidence_refs": ["sha256:" + "e" * 64],
            "artifact_refs": ["sha256:" + "f" * 64],
            "verifier_receipt_ref": "sha256:" + "1" * 64,
            "challenge_evidence_refs": ["sha256:" + "2" * 64],
            "challenge_receipt_ref": "sha256:" + "3" * 64,
            "settlement_ref": "chain:tx:1",
        },
        "command_ids": {
            "open_bounty": "cmd-open",
            "submit_candidate": "cmd-submit",
            "verify_submission": "cmd-verify",
            "open_challenge": "cmd-challenge",
            "resolve_challenge": "cmd-resolve",
            "advance_bounty": "cmd-advance",
            "settle_bounty": "cmd-settle",
            "cancel_bounty": "cmd-cancel",
        },
        "time_representatives": {
            "pre_deadline": 100,
            "at_deadline": 1000,
            "challenge_window": 1050,
            "post_challenge_window": 1101,
            "post_resolution_deadline": 1200,
        },
        "bounds": {"reward_atoms": 1000, "bond_atoms": 100, "deposit_atoms": 50},
    })
    with pytest.raises(ValueError, match="must be a string"):
        parse_market_profile(bad_semantic)


def test_profile_parsing_rejects_invalid_ref_format_in_array() -> None:
    bad_semantic = freeze_json({
        "bounty_terms": {
            "bounty_id": "bounty-1",
            "sponsor_ref": "did:example:sponsor",
            "claim_ref": "sha256:" + "a" * 64,
            "context_ref": None,
            "reward_atoms": 1000,
            "minimum_submission_bond_atoms": 100,
            "deadline_epoch_s": 1000,
            "challenge_window_seconds": 100,
            "accepted_recipe_refs": ["not-a-valid-ref"],  # Malformed: not sha256:
            "accepted_verifier_refs": ["sha256:" + "d" * 64],
        },
        "market_policy": {
            "minimum_bounty_atoms": 1000,
            "minimum_submission_bond_atoms": 100,
            "minimum_challenge_deposit_atoms": 50,
            "slashable_findings": ["invalid_signature"],
            "treasury_ref": "protocol:treasury",
            "challenge_resolution_seconds": 100,
        },
        "identities": {
            "submission_id": "submission-1",
            "challenge_id": "challenge-1",
            "sponsor_ref": "did:example:sponsor",
            "submitter_ref": "did:example:refuter",
            "challenger_ref": "did:example:challenger",
            "recipe_ref": "sha256:" + "c" * 64,
            "verifier_ref": "sha256:" + "d" * 64,
            "evidence_refs": ["sha256:" + "e" * 64],
            "artifact_refs": ["sha256:" + "f" * 64],
            "verifier_receipt_ref": "sha256:" + "1" * 64,
            "challenge_evidence_refs": ["sha256:" + "2" * 64],
            "challenge_receipt_ref": "sha256:" + "3" * 64,
            "settlement_ref": "chain:tx:1",
        },
        "command_ids": {
            "open_bounty": "cmd-open",
            "submit_candidate": "cmd-submit",
            "verify_submission": "cmd-verify",
            "open_challenge": "cmd-challenge",
            "resolve_challenge": "cmd-resolve",
            "advance_bounty": "cmd-advance",
            "settle_bounty": "cmd-settle",
            "cancel_bounty": "cmd-cancel",
        },
        "time_representatives": {
            "pre_deadline": 100,
            "at_deadline": 1000,
            "challenge_window": 1050,
            "post_challenge_window": 1101,
            "post_resolution_deadline": 1200,
        },
        "bounds": {"reward_atoms": 1000, "bond_atoms": 100, "deposit_atoms": 50},
    })
    with pytest.raises(ValueError, match="not a valid sha256 ref"):
        parse_market_profile(bad_semantic)


# ---------------------------------------------------------------------------
# Defect 4: Variant-inapplicable field rejection.
# ---------------------------------------------------------------------------

def test_command_rejects_accepted_on_non_verify() -> None:
    with pytest.raises(ValueError, match="accepted is not applicable"):
        SingleSlotAbstractCommand(kind=AbstractCommandKind.OPEN_BOUNTY, accepted=True)


def test_command_rejects_upheld_on_non_resolve() -> None:
    with pytest.raises(ValueError, match="upheld is not applicable"):
        SingleSlotAbstractCommand(kind=AbstractCommandKind.OPEN_BOUNTY, upheld=True)


def test_command_rejects_both_fields_on_simple_kind() -> None:
    with pytest.raises(ValueError):
        SingleSlotAbstractCommand(
            kind=AbstractCommandKind.ADVANCE_BOUNTY, accepted=True, upheld=False,
        )


def test_command_from_json_rejects_irrelevant_fields() -> None:
    bad_cmd = freeze_json({"kind": "open_bounty", "accepted": True})
    with pytest.raises(ValueError, match="accepted is not applicable"):
        SingleSlotAbstractCommand.from_json(bad_cmd)


def test_command_as_json_omits_irrelevant_fields() -> None:
    cmd = SingleSlotAbstractCommand(kind=AbstractCommandKind.OPEN_BOUNTY)
    j = cmd.as_json()
    assert "accepted" not in j
    assert "upheld" not in j


def test_command_as_json_includes_relevant_fields() -> None:
    cmd = SingleSlotAbstractCommand(kind=AbstractCommandKind.VERIFY_SUBMISSION, accepted=True)
    j = cmd.as_json()
    assert j["accepted"] is True
    assert "upheld" not in j


# ---------------------------------------------------------------------------
# Abstraction relation tests.
# ---------------------------------------------------------------------------

def test_concretize_initial_state_has_no_violations(profile, market) -> None:
    state = concretize_state(market, initial_abstract_state())
    violations = market_state_violations(state)
    assert violations == ()


def test_project_then_concretize_is_stable(profile, market) -> None:
    initial = concretize_state(market, initial_abstract_state())
    projected = project_state(market, initial)
    assert projected == initial_abstract_state()


# ---------------------------------------------------------------------------
# Pre-state hash enforcement (both operations).
# ---------------------------------------------------------------------------

def test_pre_state_hash_mismatch_returns_invalid_input(binding) -> None:
    initial = initial_abstract_state()
    wrong_hash = "sha256:" + "b" * 64
    req = _make_request(binding, initial.as_json(),
        freeze_json({"kind": "open_bounty"}),
        expected_pre_state_hash=wrong_hash,
    )
    resp = apply_data_adapter(load_profile(), binding, req)
    assert resp.decision_kind is AdapterDecisionKind.INVALID_INPUT
    assert resp.reason_code == InvalidInputCode.PRE_STATE_HASH_MISMATCH.value


def test_pre_state_hash_mismatch_on_validate_state(binding) -> None:
    """Defect 9: expected_pre_state_hash must be enforced for VALIDATE_STATE too."""
    initial = initial_abstract_state()
    wrong_hash = "sha256:" + "b" * 64
    req = _make_request(binding, initial.as_json(), None,
        operation=AdapterOperation.VALIDATE_STATE,
        expected_pre_state_hash=wrong_hash,
    )
    resp = apply_data_adapter(load_profile(), binding, req)
    assert resp.decision_kind is AdapterDecisionKind.INVALID_INPUT
    assert resp.reason_code == InvalidInputCode.PRE_STATE_HASH_MISMATCH.value


def test_pre_state_hash_match_proceeds(binding) -> None:
    initial = initial_abstract_state()
    correct_hash = abstract_state_hash(initial)
    req = _make_request(binding, initial.as_json(),
        freeze_json({"kind": "open_bounty"}),
        expected_pre_state_hash=correct_hash,
    )
    resp = apply_data_adapter(load_profile(), binding, req)
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT


# ---------------------------------------------------------------------------
# Binding hash enforcement.
# ---------------------------------------------------------------------------

def test_binding_hash_mismatch_returns_invalid_input(binding) -> None:
    initial = initial_abstract_state()
    wrong_binding_hash = "sha256:" + "b" * 64
    req = AdapterRequest(
        schema=REQUEST_SCHEMA,
        protocol_version=ADAPTER_PROTOCOL_VERSION,
        request_id="req-1",
        case_id="case-1",
        binding_hash=wrong_binding_hash,
        operation=AdapterOperation.VALIDATE_STATE,
        state=initial.as_json(),
        command=None,
        execution_context=ExecutionContext(time_class="pre_deadline", now_epoch_s=100),
        expected_pre_state_hash=abstract_state_hash(initial),
    )
    resp = apply_data_adapter(load_profile(), binding, req)
    assert resp.decision_kind is AdapterDecisionKind.INVALID_INPUT
    assert resp.reason_code == InvalidInputCode.BINDING_MISMATCH.value


def test_profile_hash_mismatch_returns_invalid_input(profile, binding) -> None:
    mismatched_profile = replace(profile, profile_id="different-profile")
    initial = initial_abstract_state()
    req = _make_request(
        binding,
        initial.as_json(),
        None,
        operation=AdapterOperation.VALIDATE_STATE,
    )
    resp = apply_data_adapter(mismatched_profile, binding, req)
    assert resp.decision_kind is AdapterDecisionKind.INVALID_INPUT
    assert resp.reason_code == InvalidInputCode.PROFILE_MISMATCH.value


def test_malformed_bound_profile_returns_invalid_input(profile) -> None:
    malformed_profile = replace(
        profile,
        semantic_profile=freeze_json({"wrong": "shape"}),
    )
    binding = AdapterBinding(
        schema=BINDING_SCHEMA,
        profile_hash=malformed_profile.hash(),
        source_manifest_hash="sha256:" + "a" * 64,
        model_ir_hash=None,
        protocol_version=ADAPTER_PROTOCOL_VERSION,
        adapter_implementation_id="test",
    )
    initial = initial_abstract_state()
    req = _make_request(
        binding,
        initial.as_json(),
        None,
        operation=AdapterOperation.VALIDATE_STATE,
    )
    resp = apply_data_adapter(malformed_profile, binding, req)
    assert resp.decision_kind is AdapterDecisionKind.INVALID_INPUT
    assert resp.reason_code == InvalidInputCode.PROFILE_MISMATCH.value


# ---------------------------------------------------------------------------
# Time class enforcement.
# ---------------------------------------------------------------------------

def test_time_class_mismatch_returns_invalid_input(binding) -> None:
    initial = initial_abstract_state()
    req = _make_request(binding, initial.as_json(),
        freeze_json({"kind": "open_bounty"}),
        time_class="pre_deadline",
        now_epoch_s=999,
    )
    resp = apply_data_adapter(load_profile(), binding, req)
    assert resp.decision_kind is AdapterDecisionKind.INVALID_INPUT


# ---------------------------------------------------------------------------
# Defect 7: Authoritative effect_plan_hash preservation.
# ---------------------------------------------------------------------------

def test_response_preserves_authoritative_effect_plan_hash(binding) -> None:
    initial = initial_abstract_state()
    req = _make_request(binding, initial.as_json(),
        freeze_json({"kind": "open_bounty"}))
    resp = apply_data_adapter(load_profile(), binding, req)
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    assert resp.effect_plan_hash is not None
    # The response effect_plan_hash must match the receipt's effect_plan_hash
    assert resp.receipt is not None
    assert resp.effect_plan_hash == resp.receipt["effect_plan_hash"]


# ---------------------------------------------------------------------------
# Transition parity tests.
# ---------------------------------------------------------------------------

def test_open_bounty_via_adapter(binding) -> None:
    initial = initial_abstract_state()
    req = _make_request(binding, initial.as_json(),
        freeze_json({"kind": "open_bounty"}))
    resp = apply_data_adapter(load_profile(), binding, req)
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    assert len(resp.effects) == 1
    assert resp.effects[0]["kind"] == "lock_escrow"
    assert resp.receipt is not None
    assert resp.receipt["event_kind"] == "bounty_opened"
    assert resp.post_state["phase"] == "open"
    assert resp.post_state["escrow_atoms"] == 1000


def test_full_lifecycle_via_adapter(binding) -> None:
    state = initial_abstract_state()

    # 1. Open bounty
    resp = apply_data_adapter(load_profile(), binding, _make_request(binding, state.as_json(),
        freeze_json({"kind": "open_bounty"})))
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    state = SingleSlotAbstractState.from_json(resp.post_state)

    # 2. Submit candidate
    resp = apply_data_adapter(load_profile(), binding, _make_request(binding, state.as_json(),
        freeze_json({"kind": "submit_candidate"}),
        time_class="pre_deadline", now_epoch_s=100))
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    state = SingleSlotAbstractState.from_json(resp.post_state)
    assert state.submission_status is AbstractSubmissionStatus.PENDING
    assert state.submission_time_class is TimeClassOrNone.PRE_DEADLINE

    # 3. Verify submission (accepted)
    resp = apply_data_adapter(load_profile(), binding, _make_request(binding, state.as_json(),
        freeze_json({"kind": "verify_submission", "accepted": True}),
        time_class="challenge_window", now_epoch_s=1050))
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    state = SingleSlotAbstractState.from_json(resp.post_state)
    assert state.submission_status is AbstractSubmissionStatus.VERIFIED

    # 4. Advance to payable
    resp = apply_data_adapter(load_profile(), binding, _make_request(binding, state.as_json(),
        freeze_json({"kind": "advance_bounty"}),
        time_class="post_challenge_window", now_epoch_s=1101))
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    state = SingleSlotAbstractState.from_json(resp.post_state)
    assert state.phase is AbstractPhase.PAYABLE

    # 5. Settle
    resp = apply_data_adapter(load_profile(), binding, _make_request(binding, state.as_json(),
        freeze_json({"kind": "settle_bounty"}),
        time_class="post_resolution_deadline", now_epoch_s=1200))
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    state = SingleSlotAbstractState.from_json(resp.post_state)
    assert state.phase is AbstractPhase.SETTLED
    assert state.escrow_atoms == 0


def test_committed_failure_is_distinct(binding) -> None:
    state = initial_abstract_state()

    # Open bounty
    resp = apply_data_adapter(load_profile(), binding, _make_request(binding, state.as_json(),
        freeze_json({"kind": "open_bounty"})))
    state = SingleSlotAbstractState.from_json(resp.post_state)

    # Submit candidate
    resp = apply_data_adapter(load_profile(), binding, _make_request(binding, state.as_json(),
        freeze_json({"kind": "submit_candidate"})))
    state = SingleSlotAbstractState.from_json(resp.post_state)

    # Verify submission (rejected) → committed failure
    resp = apply_data_adapter(load_profile(), binding, _make_request(binding, state.as_json(),
        freeze_json({"kind": "verify_submission", "accepted": False}),
        time_class="challenge_window", now_epoch_s=1050))
    assert resp.decision_kind is AdapterDecisionKind.COMMITTED_FAILURE
    assert resp.reason_code is not None
    assert resp.post_state is not None
    assert len(resp.effects) == 1
    assert resp.effects[0]["kind"] == "refund_submission_bond"
    assert resp.receipt is not None
    # Effect plan hash must be authoritative
    assert resp.effect_plan_hash == resp.receipt["effect_plan_hash"]


# ---------------------------------------------------------------------------
# Reject leaves state unchanged.
# ---------------------------------------------------------------------------

def test_reject_leaves_state_unchanged(binding) -> None:
    initial = initial_abstract_state()
    req = _make_request(binding, initial.as_json(),
        freeze_json({"kind": "submit_candidate"}))
    resp = apply_data_adapter(load_profile(), binding, req)
    assert resp.decision_kind is AdapterDecisionKind.REJECT
    assert resp.post_state == resp.pre_state
    assert resp.post_state_hash == resp.pre_state_hash
    assert resp.effects == ()
    assert resp.receipt is None
    assert resp.effect_plan_hash is None


# ---------------------------------------------------------------------------
# No synthetic commands — time from execution_context.
# ---------------------------------------------------------------------------

def test_no_close_deadline_command_in_profile() -> None:
    assert "close_deadline" not in {c.value for c in AbstractCommandKind}
    assert "close_challenge_window" not in {c.value for c in AbstractCommandKind}
    assert "advance_bounty" in {c.value for c in AbstractCommandKind}


def test_time_comes_from_execution_context(binding) -> None:
    initial = initial_abstract_state()
    req = _make_request(binding, initial.as_json(),
        freeze_json({"kind": "open_bounty"}),
        now_epoch_s=100)
    resp = apply_data_adapter(load_profile(), binding, req)
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    assert resp.receipt["occurred_at"] == 100


# ---------------------------------------------------------------------------
# Duplicate command rejected.
# ---------------------------------------------------------------------------

def test_duplicate_command_rejected(binding) -> None:
    state = initial_abstract_state()
    cmd = freeze_json({"kind": "open_bounty"})
    resp1 = apply_data_adapter(load_profile(), binding, _make_request(binding, state.as_json(), cmd))
    assert resp1.decision_kind is AdapterDecisionKind.ACCEPT
    state_after = SingleSlotAbstractState.from_json(resp1.post_state)
    resp2 = apply_data_adapter(load_profile(), binding, _make_request(binding, state_after.as_json(), cmd))
    assert resp2.decision_kind is AdapterDecisionKind.REJECT
    assert resp2.reason_code == "DUPLICATE_COMMAND"


# ---------------------------------------------------------------------------
# VALIDATE_STATE operation.
# ---------------------------------------------------------------------------

def test_validate_state_valid(binding) -> None:
    initial = initial_abstract_state()
    req = _make_request(binding, initial.as_json(), None,
        operation=AdapterOperation.VALIDATE_STATE)
    resp = apply_data_adapter(load_profile(), binding, req)
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    assert resp.state_violations == ()


def test_validate_state_invalid(binding) -> None:
    bad_state = freeze_json({
        "phase": "draft", "escrow_atoms": 999,
        "submission_status": "none", "submission_time_class": "none",
        "bond_atoms": 0,
        "challenge_status": "none", "challenge_opened_time_class": "none",
        "deposit_atoms": 0, "payable": False, "settled": False,
        "processed_command_mask": 0,
    })
    bad_abstract = SingleSlotAbstractState.from_json(bad_state)
    req = _make_request(binding, bad_state, None,
        operation=AdapterOperation.VALIDATE_STATE,
        expected_pre_state_hash=abstract_state_hash(bad_abstract))
    resp = apply_data_adapter(load_profile(), binding, req)
    # draft with escrow is invalid per market invariants
    assert resp.decision_kind is AdapterDecisionKind.REJECT
    assert resp.reason_code == "INVALID_STATE"


def test_validate_state_rejects_settlement_ref_outside_settled_phase(binding) -> None:
    expired_with_settlement = freeze_json({
        "phase": "expired", "escrow_atoms": 0,
        "submission_status": "none", "submission_time_class": "none",
        "bond_atoms": 0,
        "challenge_status": "none", "challenge_opened_time_class": "none",
        "deposit_atoms": 0, "payable": False, "settled": True,
        "processed_command_mask": 0,
    })
    abstract = SingleSlotAbstractState.from_json(expired_with_settlement)
    request = _make_request(
        binding,
        expired_with_settlement,
        None,
        operation=AdapterOperation.VALIDATE_STATE,
        expected_pre_state_hash=abstract_state_hash(abstract),
    )

    response = apply_data_adapter(load_profile(), binding, request)

    assert response.decision_kind is AdapterDecisionKind.REJECT
    assert response.reason_code == "INVALID_STATE"
    assert any(
        violation["code"] == "non_settled_has_settlement"
        for violation in response.state_violations
    )


# ---------------------------------------------------------------------------
# INVALID_INPUT for out-of-domain abstract state.
# ---------------------------------------------------------------------------

def test_invalid_state_out_of_domain(binding) -> None:
    bad_state = freeze_json({"phase": "nonexistent", "escrow_atoms": 0,
        "submission_status": "none", "submission_time_class": "none",
        "bond_atoms": 0,
        "challenge_status": "none", "challenge_opened_time_class": "none",
        "deposit_atoms": 0, "payable": False, "settled": False,
        "processed_command_mask": 0})
    req = AdapterRequest(
        schema=REQUEST_SCHEMA,
        protocol_version=ADAPTER_PROTOCOL_VERSION,
        request_id="req-1",
        case_id="case-1",
        binding_hash=binding.hash(),
        operation=AdapterOperation.VALIDATE_STATE,
        state=bad_state,
        command=None,
        execution_context=ExecutionContext(time_class="pre_deadline", now_epoch_s=100),
        expected_pre_state_hash="sha256:" + "0" * 64,
    )
    resp = apply_data_adapter(load_profile(), binding, req)
    assert resp.decision_kind is AdapterDecisionKind.INVALID_INPUT


def test_invalid_command_out_of_domain(binding) -> None:
    initial = initial_abstract_state()
    bad_cmd = freeze_json({"kind": "nonexistent_command"})
    req = _make_request(binding, initial.as_json(), bad_cmd)
    resp = apply_data_adapter(load_profile(), binding, req)
    assert resp.decision_kind is AdapterDecisionKind.INVALID_INPUT


# ---------------------------------------------------------------------------
# Market state violations are typed.
# ---------------------------------------------------------------------------

def test_market_state_violations_are_typed() -> None:
    violations = market_state_violations("not a state")
    assert len(violations) == 1
    v = violations[0]
    assert v.code is MarketStateViolationCode.STATE_TYPE
    assert v.field_path == "$"
    assert isinstance(v.detail, str)


# ---------------------------------------------------------------------------
# Defect 9: Source manifest and binding hash verification.
# ---------------------------------------------------------------------------

def test_load_source_manifest_verifies_profile_hash(profile) -> None:
    manifest = load_source_manifest(profile)
    assert manifest.profile_hash == profile.hash()


def test_load_source_manifest_rejects_tampered_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile,
) -> None:
    import popperpad.refinement.profiles.market_single_slot_v1 as profile_module

    source = Path(profile_module.__file__).parent / "market_single_slot_v1.sources.json"
    raw = json.loads(source.read_text(encoding="utf-8"))
    raw["schema"] = "popperpad/data-adapter-source-manifest/v0"
    tampered = tmp_path / "market_single_slot_v1.sources.json"
    tampered.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(profile_module, "_SOURCE_MANIFEST_PATH", tampered)

    with pytest.raises(ValueError, match="SourceManifest.schema mismatch"):
        profile_module.load_source_manifest(profile)


def test_load_binding_verifies_hashes(profile) -> None:
    manifest = load_source_manifest(profile)
    binding = load_binding(profile, manifest)
    assert binding.profile_hash == profile.hash()
    assert binding.source_manifest_hash == manifest.hash()


def test_load_binding_fails_on_stale_manifest(profile) -> None:
    """If the manifest's profile_hash doesn't match, loading must fail-closed."""
    from popperpad.core.adapter_protocol import SourceFileBinding, SourceManifest, SOURCE_MANIFEST_SCHEMA
    stale_manifest = SourceManifest(
        schema=SOURCE_MANIFEST_SCHEMA,
        repository="test",
        commit="a" * 40,
        files=(SourceFileBinding(path="src/test.py", sha256="sha256:" + "a" * 64),),
        profile_hash="sha256:" + "b" * 64,  # Wrong hash
        codec_version="popperpad-json-int-v2",
    )
    with pytest.raises(ValueError, match="does not match"):
        load_binding(profile, stale_manifest)


def test_source_manifest_verifies_live_bytes_and_rejects_tamper(
    tmp_path: Path,
    profile,
) -> None:
    source = tmp_path / "src" / "example.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"trusted source\n")
    manifest = SourceManifest(
        schema=SOURCE_MANIFEST_SCHEMA,
        repository="test/repository",
        commit="a" * 40,
        files=(
            SourceFileBinding(
                path="src/example.py",
                sha256=sha256_bytes(b"trusted source\n"),
            ),
        ),
        profile_hash=profile.hash(),
        codec_version="popperpad-json-int-v2",
    )
    verify_source_manifest_files(manifest, source_roots=(tmp_path,))
    source.write_bytes(b"tampered source\n")
    with pytest.raises(ValueError, match="source digest mismatch"):
        verify_source_manifest_files(manifest, source_roots=(tmp_path,))


def test_profile_and_source_manifest_are_packaged_resources() -> None:
    import popperpad.refinement.profiles.market_single_slot_v1 as profile_module

    resource_dir = Path(profile_module.__file__).parent
    assert (resource_dir / "market_single_slot_v1.json").is_file()
    assert (resource_dir / "market_single_slot_v1.sources.json").is_file()


# ---------------------------------------------------------------------------
# Complete BFS enumeration.
# ---------------------------------------------------------------------------

def test_complete_enumeration_search_completes(profile, binding) -> None:
    from popperpad.refinement.enumerator import enumerate_all_transitions

    result = enumerate_all_transitions(profile, binding)
    assert result.search_complete is True
    assert result.budget_exhausted is False
    assert result.reachable_states > 0
    assert result.total_cases > 0
    assert result.accept_count > 0
    assert result.reject_count > 0
    assert type(result.reject_reasons) is FrozenDict
    with pytest.raises(TypeError):
        result.reject_reasons["mutated"] = 1


def test_enumeration_enforces_state_budget_per_successor(profile, binding) -> None:
    from popperpad.refinement.enumerator import enumerate_all_transitions

    result = enumerate_all_transitions(profile, binding, max_states=3)

    assert result.reachable_states == 3
    assert result.search_complete is False
    assert result.budget_exhausted is True


@pytest.mark.parametrize("max_states", [0, -1, True, 3.5])
def test_enumeration_rejects_invalid_state_budgets(
    profile,
    binding,
    max_states,
) -> None:
    from popperpad.refinement.enumerator import enumerate_all_transitions

    with pytest.raises(ValueError, match="max_states must be a positive integer"):
        enumerate_all_transitions(profile, binding, max_states=max_states)


def test_enumeration_corpus_hash_is_deterministic(profile, binding) -> None:
    from popperpad.refinement.enumerator import enumerate_all_transitions

    result1 = enumerate_all_transitions(profile, binding)
    result2 = enumerate_all_transitions(profile, binding)
    assert result1.corpus_hash == result2.corpus_hash


def test_enumeration_covers_all_command_variants(profile, binding) -> None:
    from popperpad.refinement.enumerator import enumerate_all_transitions

    result = enumerate_all_transitions(profile, binding)
    assert result.command_variants == 10
    assert result.time_classes == 5


def test_enumeration_uses_supplied_profile_time_representatives(profile, binding) -> None:
    from popperpad.refinement.enumerator import enumerate_all_transitions

    semantic = thaw_json(profile.semantic_profile)
    assert isinstance(semantic, dict)
    semantic["time_representatives"] = {
        "pre_deadline": 101,
        "at_deadline": 1001,
        "challenge_window": 1051,
        "post_challenge_window": 1102,
        "post_resolution_deadline": 1201,
    }
    shifted_semantic = freeze_json(semantic)
    assert isinstance(shifted_semantic, FrozenDict)
    shifted_profile = replace(profile, semantic_profile=shifted_semantic)
    shifted_binding = replace(binding, profile_hash=shifted_profile.hash())

    result = enumerate_all_transitions(shifted_profile, shifted_binding)

    assert result.search_complete is True
    assert result.reachable_states > 1
    assert result.accept_count > 0
