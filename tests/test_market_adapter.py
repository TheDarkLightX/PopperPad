"""Tests for the bounded falsification-market adapter (PR A2).

Tests verify:
- Architecture: adapter imports core, not vice versa; shell has no market semantics.
- Abstraction relation: representability, projection stability, decision refinement.
- Transition parity: all reachable profile states × commands × time-classes.
- Rejection precedence: earlier rejection classes dominate later.
- Exact effects and receipts: not cumulative counters.
- No synthetic commands: time comes from execution_context.
- JSONL shell: one-shot, persistent, malformed recovery, deterministic replay.
"""

from __future__ import annotations

import ast
import io
import json
from pathlib import Path

import pytest

from popperpad.core.adapter_protocol import (
    AdapterDecisionKind,
    AdapterOperation,
    AdapterRequest,
    ExecutionContext,
    MarketAdapterProfile,
)
from popperpad.core.market import (
    BountyPhase,
    BountyState,
    BountyTerms,
    MarketPolicy,
    Amount,
    initial_bounty,
    apply_market_command,
    OpenBounty,
    SubmitCandidate,
    VerifySubmission,
    OpenChallenge,
    ResolveChallenge,
    AdvanceBounty,
    SettleBounty,
    CancelBounty,
    Payout,
)
from popperpad.core.market_invariants import market_state_violations, MarketStateViolationCode
from popperpad.core.values import FrozenDict, freeze_json, thaw_json
from popperpad.refinement.market_adapter import (
    apply_data_adapter,
    concretize_state,
    concretize_command,
    project_state,
    project_decision,
)
from popperpad.refinement.profiles.market_single_slot_v1 import load_profile


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------

@pytest.fixture
def profile() -> MarketAdapterProfile:
    return load_profile()


def _initial_abstract_state(profile: MarketAdapterProfile) -> FrozenDict:
    return freeze_json({
        "terms": dict(profile.bounty_terms_json.items()),
        "phase": "draft",
        "escrow_locked_atoms": 0,
        "submissions": [],
        "challenges": [],
        "payable_submission_ids": [],
        "settlement_ref": None,
        "processed_command_ids": [],
    })


def _make_request(
    profile: MarketAdapterProfile,
    state: FrozenDict,
    command: FrozenDict | None = None,
    operation: AdapterOperation = AdapterOperation.STEP,
    time_class: str = "pre_deadline",
    now_epoch_s: int = 100,
    request_id: str = "req-1",
) -> AdapterRequest:
    return AdapterRequest(
        schema="popperpad/data-adapter-protocol/v1",
        protocol_version="v1",
        request_id=request_id,
        case_id="case-1",
        profile_id=profile.profile_id,
        profile_hash=profile.hash(),
        source_manifest_hash=profile.source_manifest_hash,
        model_ir_hash=profile.model_ir_hash,
        operation=operation,
        state=state,
        command=command,
        execution_context=ExecutionContext(time_class=time_class, now_epoch_s=now_epoch_s),
        expected_pre_state_hash="sha256:" + "0" * 64,
    )


def _cmd(kind: str, **fields) -> FrozenDict:
    return freeze_json({"kind": kind, **fields})


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


def test_shell_has_no_forbidden_imports() -> None:
    path = Path(__import__("popperpad.shells.data_adapter_jsonl", fromlist=["__file__"]).__file__)
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
# Abstraction relation: representability.
# ---------------------------------------------------------------------------

def test_concretize_initial_state_has_no_violations(profile: MarketAdapterProfile) -> None:
    state = concretize_state(profile, _initial_abstract_state(profile))
    violations = market_state_violations(state)
    assert violations == ()


def test_project_then_concretize_is_stable(profile: MarketAdapterProfile) -> None:
    initial = concretize_state(profile, _initial_abstract_state(profile))
    projected = project_state(profile, initial)
    reconcretized = concretize_state(profile, projected)
    assert project_state(profile, reconcretized) == projected


# ---------------------------------------------------------------------------
# Transition parity: open_bounty.
# ---------------------------------------------------------------------------

def test_open_bounty_via_adapter_matches_core(profile: MarketAdapterProfile) -> None:
    initial = _initial_abstract_state(profile)
    cmd = _cmd("open_bounty", command_id="cmd-1", funded_atoms=1000)
    req = _make_request(profile, initial, cmd, now_epoch_s=100)
    resp = apply_data_adapter(profile, req)
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    assert len(resp.effects) == 1
    assert resp.effects[0]["kind"] == "lock_escrow"
    assert resp.receipt is not None
    assert resp.receipt["event_kind"] == "bounty_opened"
    assert resp.post_state["phase"] == "open"
    assert resp.post_state["escrow_locked_atoms"] == 1000


def test_open_bounty_wrong_phase_rejected(profile: MarketAdapterProfile) -> None:
    open_state = freeze_json({
        "terms": dict(profile.bounty_terms_json.items()),
        "phase": "open",
        "escrow_locked_atoms": 1000,
        "submissions": [],
        "challenges": [],
        "payable_submission_ids": [],
        "settlement_ref": None,
        "processed_command_ids": ["cmd-1"],
    })
    cmd = _cmd("open_bounty", command_id="cmd-2", funded_atoms=1000)
    req = _make_request(profile, open_state, cmd, now_epoch_s=100)
    resp = apply_data_adapter(profile, req)
    assert resp.decision_kind is AdapterDecisionKind.REJECT
    assert resp.reason_code == "WRONG_PHASE"
    assert resp.effects == ()
    assert resp.receipt is None
    assert resp.post_state == resp.pre_state


def test_reject_leaves_state_unchanged(profile: MarketAdapterProfile) -> None:
    initial = _initial_abstract_state(profile)
    cmd = _cmd("submit_candidate", command_id="cmd-1", submission_id="sub-1", bond_atoms=50)
    req = _make_request(profile, initial, cmd, now_epoch_s=100)
    resp = apply_data_adapter(profile, req)
    assert resp.decision_kind is AdapterDecisionKind.REJECT
    assert resp.reason_code == "WRONG_PHASE"
    assert resp.post_state == resp.pre_state
    assert resp.post_state_hash == resp.pre_state_hash
    assert resp.effects == ()
    assert resp.receipt is None


# ---------------------------------------------------------------------------
# Full lifecycle parity via adapter.
# ---------------------------------------------------------------------------

def test_full_lifecycle_via_adapter(profile: MarketAdapterProfile) -> None:
    state = _initial_abstract_state(profile)

    # 1. Open bounty
    resp = apply_data_adapter(profile, _make_request(profile, state,
        _cmd("open_bounty", command_id="cmd-open", funded_atoms=1000), now_epoch_s=100))
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    state = resp.post_state

    # 2. Submit candidate
    resp = apply_data_adapter(profile, _make_request(profile, state,
        _cmd("submit_candidate", command_id="cmd-submit", submission_id="sub-1", bond_atoms=100),
        now_epoch_s=200))
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    state = resp.post_state
    assert len(state["submissions"]) == 1

    # 3. Verify submission (accepted)
    resp = apply_data_adapter(profile, _make_request(profile, state,
        _cmd("verify_submission", command_id="cmd-verify", submission_id="sub-1", accepted=True),
        now_epoch_s=300, time_class="challenge_window"))
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    state = resp.post_state
    assert state["submissions"][0]["status"] == "verified"

    # 4. Advance to payable
    resp = apply_data_adapter(profile, _make_request(profile, state,
        _cmd("advance_bounty", command_id="cmd-advance"),
        now_epoch_s=1101, time_class="post_challenge_window"))
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    state = resp.post_state
    assert state["phase"] == "payable"

    # 5. Settle
    resp = apply_data_adapter(profile, _make_request(profile, state,
        _cmd("settle_bounty", command_id="cmd-settle",
             payouts=[{"recipient_ref": "did:example:refuter", "submission_id": "sub-1", "amount_atoms": 1000}]),
        now_epoch_s=1200, time_class="post_resolution_deadline"))
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    state = resp.post_state
    assert state["phase"] == "settled"
    assert state["escrow_locked_atoms"] == 0


# ---------------------------------------------------------------------------
# Committed failure is distinct from Reject and Accept.
# ---------------------------------------------------------------------------

def test_committed_failure_is_distinct(profile: MarketAdapterProfile) -> None:
    state = _initial_abstract_state(profile)
    # Open bounty
    resp = apply_data_adapter(profile, _make_request(profile, state,
        _cmd("open_bounty", command_id="cmd-open", funded_atoms=1000), now_epoch_s=100))
    state = resp.post_state
    # Submit candidate
    resp = apply_data_adapter(profile, _make_request(profile, state,
        _cmd("submit_candidate", command_id="cmd-submit", submission_id="sub-1", bond_atoms=100),
        now_epoch_s=200))
    state = resp.post_state
    # Verify submission (rejected) → committed failure
    resp = apply_data_adapter(profile, _make_request(profile, state,
        _cmd("verify_submission", command_id="cmd-verify", submission_id="sub-1", accepted=False),
        now_epoch_s=300, time_class="challenge_window"))
    assert resp.decision_kind is AdapterDecisionKind.COMMITTED_FAILURE
    assert resp.reason_code is not None
    assert resp.post_state is not None
    assert len(resp.effects) == 1
    assert resp.effects[0]["kind"] == "refund_submission_bond"
    assert resp.receipt is not None


# ---------------------------------------------------------------------------
# No synthetic commands — time comes from execution_context.
# ---------------------------------------------------------------------------

def test_no_close_deadline_command_in_profile(profile: MarketAdapterProfile) -> None:
    assert "close_deadline" not in profile.allowed_abstract_commands
    assert "close_challenge_window" not in profile.allowed_abstract_commands
    assert "advance_bounty" in profile.allowed_abstract_commands


def test_time_comes_from_execution_context(profile: MarketAdapterProfile) -> None:
    initial = _initial_abstract_state(profile)
    cmd = _cmd("open_bounty", command_id="cmd-1", funded_atoms=1000)
    req = _make_request(profile, initial, cmd, now_epoch_s=100)
    resp = apply_data_adapter(profile, req)
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    assert resp.receipt["occurred_at"] == 100


# ---------------------------------------------------------------------------
# Exact effects, not cumulative counters.
# ---------------------------------------------------------------------------

def test_effects_are_exact_not_counters(profile: MarketAdapterProfile) -> None:
    state = _initial_abstract_state(profile)
    resp = apply_data_adapter(profile, _make_request(profile, state,
        _cmd("open_bounty", command_id="cmd-open", funded_atoms=1000), now_epoch_s=100))
    assert len(resp.effects) == 1
    effect = resp.effects[0]
    assert "kind" in effect
    assert "account_ref" in effect
    assert "amount_atoms" in effect
    assert "subject_ref" in effect
    assert "metadata" in effect
    assert effect["amount_atoms"] == 1000


# ---------------------------------------------------------------------------
# Duplicate command does not duplicate effects.
# ---------------------------------------------------------------------------

def test_duplicate_command_rejected(profile: MarketAdapterProfile) -> None:
    state = _initial_abstract_state(profile)
    cmd = _cmd("open_bounty", command_id="cmd-dup", funded_atoms=1000)
    resp1 = apply_data_adapter(profile, _make_request(profile, state, cmd, now_epoch_s=100))
    assert resp1.decision_kind is AdapterDecisionKind.ACCEPT
    state_after = resp1.post_state
    resp2 = apply_data_adapter(profile, _make_request(profile, state_after, cmd, now_epoch_s=100))
    assert resp2.decision_kind is AdapterDecisionKind.REJECT
    assert resp2.reason_code == "DUPLICATE_COMMAND"
    assert resp2.effects == ()


# ---------------------------------------------------------------------------
# Receipt state hash is bound to the returned state.
# ---------------------------------------------------------------------------

def test_receipt_state_hash_matches_post_state_hash(profile: MarketAdapterProfile) -> None:
    state = _initial_abstract_state(profile)
    resp = apply_data_adapter(profile, _make_request(profile, state,
        _cmd("open_bounty", command_id="cmd-1", funded_atoms=1000), now_epoch_s=100))
    assert resp.receipt is not None
    assert resp.receipt["state_hash"] == resp.post_state_hash


# ---------------------------------------------------------------------------
# Market state violations are typed, not bare strings.
# ---------------------------------------------------------------------------

def test_market_state_violations_are_typed() -> None:
    violations = market_state_violations("not a state")
    assert len(violations) == 1
    v = violations[0]
    assert v.code is MarketStateViolationCode.STATE_TYPE
    assert v.field_path == "$"
    assert isinstance(v.detail, str)
    assert isinstance(v.render(), str)


def test_market_state_violations_empty_for_valid_state(profile: MarketAdapterProfile) -> None:
    state = concretize_state(profile, _initial_abstract_state(profile))
    assert market_state_violations(state) == ()


# ---------------------------------------------------------------------------
# JSONL shell tests.
# ---------------------------------------------------------------------------

def _jsonl_request(profile: MarketAdapterProfile, state: FrozenDict, command: dict | None = None,
                    operation: str = "step", time_class: str = "pre_deadline", now: int = 100) -> str:
    state_plain = thaw_json(state) if isinstance(state, FrozenDict) else state
    return json.dumps({
        "schema": "popperpad/data-adapter-protocol/v1",
        "protocol_version": "v1",
        "request_id": "req-1",
        "case_id": "case-1",
        "profile_id": profile.profile_id,
        "profile_hash": profile.hash(),
        "source_manifest_hash": profile.source_manifest_hash,
        "model_ir_hash": profile.model_ir_hash,
        "operation": operation,
        "state": state_plain,
        "command": command,
        "execution_context": {"time_class": time_class, "now_epoch_s": now},
        "expected_pre_state_hash": "sha256:" + "0" * 64,
    }, sort_keys=True)


def test_jsonl_one_shot_mode(profile: MarketAdapterProfile) -> None:
    from popperpad.shells.data_adapter_jsonl import run_one_shot

    initial = _initial_abstract_state(profile)
    cmd = {"kind": "open_bounty", "command_id": "cmd-1", "funded_atoms": 1000}
    line = _jsonl_request(profile, initial, cmd)
    stdin = io.StringIO(line + "\n")
    stdout = io.StringIO()
    stderr = io.StringIO()
    run_one_shot(profile, stdin, stdout, stderr)
    output = stdout.getvalue().strip()
    assert output
    response = json.loads(output)
    assert response["decision_kind"] == "accept"
    assert response["receipt"]["event_kind"] == "bounty_opened"


def test_jsonl_persistent_mode_multiple_requests(profile: MarketAdapterProfile) -> None:
    from popperpad.shells.data_adapter_jsonl import run_persistent

    initial = _initial_abstract_state(profile)
    cmd1 = {"kind": "open_bounty", "command_id": "cmd-1", "funded_atoms": 1000}
    line1 = _jsonl_request(profile, initial, cmd1)
    # Second request: validate the initial state independently
    line2 = _jsonl_request(profile, initial, None, operation="validate_state")
    stdin = io.StringIO(line1 + "\n" + line2 + "\n")
    stdout = io.StringIO()
    stderr = io.StringIO()
    run_persistent(profile, stdin, stdout, stderr)
    lines = stdout.getvalue().strip().split("\n")
    assert len(lines) == 2
    r1 = json.loads(lines[0])
    r2 = json.loads(lines[1])
    assert r1["decision_kind"] == "accept"
    assert r2["decision_kind"] == "accept"


def test_jsonl_malformed_input_returns_invalid_input(profile: MarketAdapterProfile) -> None:
    from popperpad.shells.data_adapter_jsonl import run_persistent

    stdin = io.StringIO("not valid json\n")
    stdout = io.StringIO()
    stderr = io.StringIO()
    rc = run_persistent(profile, stdin, stdout, stderr)
    assert rc == 0
    output = stdout.getvalue().strip()
    assert output
    response = json.loads(output)
    assert response["decision_kind"] == "invalid_input"


def test_jsonl_float_rejected(profile: MarketAdapterProfile) -> None:
    from popperpad.shells.data_adapter_jsonl import run_persistent

    initial = _initial_abstract_state(profile)
    line = _jsonl_request(profile, initial, None, operation="validate_state")
    line = line.replace('"phase": "draft"', '"phase": 3.14')
    stdin = io.StringIO(line + "\n")
    stdout = io.StringIO()
    stderr = io.StringIO()
    run_persistent(profile, stdin, stdout, stderr)
    response = json.loads(stdout.getvalue().strip())
    assert response["decision_kind"] == "invalid_input"


def test_jsonl_deterministic_replay(profile: MarketAdapterProfile) -> None:
    from popperpad.shells.data_adapter_jsonl import run_one_shot

    initial = _initial_abstract_state(profile)
    cmd = {"kind": "open_bounty", "command_id": "cmd-1", "funded_atoms": 1000}
    line = _jsonl_request(profile, initial, cmd)

    outputs = []
    for _ in range(3):
        stdin = io.StringIO(line + "\n")
        stdout = io.StringIO()
        stderr = io.StringIO()
        run_one_shot(profile, stdin, stdout, stderr)
        outputs.append(stdout.getvalue().strip())
    assert outputs[0] == outputs[1] == outputs[2]


# ---------------------------------------------------------------------------
# VALIDATE_STATE operation.
# ---------------------------------------------------------------------------

def test_validate_state_valid(profile: MarketAdapterProfile) -> None:
    initial = _initial_abstract_state(profile)
    req = _make_request(profile, initial, None, operation=AdapterOperation.VALIDATE_STATE)
    resp = apply_data_adapter(profile, req)
    assert resp.decision_kind is AdapterDecisionKind.ACCEPT
    assert resp.state_violations == ()


def test_validate_state_invalid(profile: MarketAdapterProfile) -> None:
    bad_state = freeze_json({
        "terms": dict(profile.bounty_terms_json.items()),
        "phase": "draft",
        "escrow_locked_atoms": 999,
        "submissions": [],
        "challenges": [],
        "payable_submission_ids": [],
        "settlement_ref": None,
        "processed_command_ids": [],
    })
    req = _make_request(profile, bad_state, None, operation=AdapterOperation.VALIDATE_STATE)
    resp = apply_data_adapter(profile, req)
    assert resp.decision_kind is AdapterDecisionKind.REJECT
    assert resp.reason_code == "INVALID_STATE"
    assert len(resp.state_violations) > 0


# ---------------------------------------------------------------------------
# INVALID_INPUT for out-of-domain abstract state.
# ---------------------------------------------------------------------------

def test_invalid_state_out_of_domain(profile: MarketAdapterProfile) -> None:
    bad_state = freeze_json({"phase": "nonexistent_phase", "escrow_locked_atoms": 0})
    req = _make_request(profile, bad_state, None, operation=AdapterOperation.VALIDATE_STATE)
    resp = apply_data_adapter(profile, req)
    assert resp.decision_kind is AdapterDecisionKind.INVALID_INPUT
    assert resp.post_state is None
    assert resp.effects == ()
    assert resp.receipt is None


def test_invalid_command_out_of_domain(profile: MarketAdapterProfile) -> None:
    initial = _initial_abstract_state(profile)
    bad_cmd = freeze_json({"kind": "nonexistent_command", "command_id": "cmd-1"})
    req = _make_request(profile, initial, bad_cmd)
    resp = apply_data_adapter(profile, req)
    assert resp.decision_kind is AdapterDecisionKind.INVALID_INPUT
