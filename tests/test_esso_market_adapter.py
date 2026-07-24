from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from popperpad.core.codec import canonical_json_bytes
from popperpad.esso_market_adapter import (
    ABSTRACTION_ID,
    SCHEMA,
    AbstractMarketState,
    initial_abstract_state,
    step_document,
)


def doc(state: AbstractMarketState, kind: str) -> dict:
    return {
        "schema": SCHEMA,
        "abstraction_id": ABSTRACTION_ID,
        "state": json.loads(canonical_json_bytes(state.as_json())),
        "command": {"kind": kind},
    }


def step(state: AbstractMarketState, kind: str) -> tuple[AbstractMarketState, dict]:
    result = step_document(doc(state, kind))
    return AbstractMarketState.from_mapping(result["state"]), result


def test_mounted_adapter_happy_path_and_exact_conservation() -> None:
    state = initial_abstract_state()
    state, opened = step(state, "open_bounty")
    assert opened["decision_kind"] == "accept"
    assert state.escrow_atoms == 2

    state, _ = step(state, "submit_candidate")
    assert state.submission == "Pending"
    assert state.bond_atoms == 1

    state, _ = step(state, "verify_accept")
    assert state.submission == "Verified"

    state, _ = step(state, "close_deadline")
    state, _ = step(state, "close_challenge_window")
    state, payable = step(state, "advance")
    assert payable["effects"]["event"] == "EventPayable"
    assert state.phase == "Payable"

    state, settled = step(state, "settle")
    assert settled["decision_kind"] == "accept"
    assert state.phase == "Settled"
    assert state.escrow_atoms == 0
    assert state.payout_atoms == 2
    assert state.bond_atoms == 0
    assert state.bond_refund_atoms == 1
    assert settled["state_violations"] == []


def test_challenge_can_be_resolved_after_window_then_advance() -> None:
    state = initial_abstract_state()
    for kind in ("open_bounty", "submit_candidate", "verify_accept", "close_deadline"):
        state, _ = step(state, kind)
    state, _ = step(state, "open_challenge")
    state, _ = step(state, "close_challenge_window")

    unchanged, blocked = step(state, "advance")
    assert blocked["decision_kind"] == "reject"
    assert blocked["reason_code"] == "POLICY_MISMATCH"
    assert unchanged == state

    state, resolved = step(state, "resolve_rejected")
    assert resolved["decision_kind"] == "committed_failure"
    assert resolved["reason_code"] == "CHALLENGE_REJECTED"
    assert state.challenge == "Rejected"
    assert state.deposit_slashed_atoms == 1

    state, advanced = step(state, "advance")
    assert advanced["decision_kind"] == "accept"
    assert state.phase == "Payable"


def test_honest_verifier_rejection_refunds_and_never_slashes() -> None:
    state = initial_abstract_state()
    state, _ = step(state, "open_bounty")
    state, _ = step(state, "submit_candidate")
    state, result = step(state, "verify_reject")
    assert result["decision_kind"] == "committed_failure"
    assert state.submission == "Rejected"
    assert state.bond_atoms == 0
    assert state.bond_refund_atoms == 1
    assert state.bond_slashed_atoms == 0


def test_upheld_challenge_is_the_only_bond_slash_path() -> None:
    state = initial_abstract_state()
    for kind in ("open_bounty", "submit_candidate", "verify_accept", "open_challenge"):
        state, _ = step(state, kind)
    state, result = step(state, "resolve_upheld")
    assert result["decision_kind"] == "accept"
    assert state.challenge == "Upheld"
    assert state.submission == "Rejected"
    assert state.bond_slashed_atoms == 1
    assert state.deposit_refund_atoms == 1
    assert state.bond_refund_atoms == 0


def test_late_new_challenge_rejects_but_existing_challenge_resolution_does_not() -> None:
    state = initial_abstract_state()
    for kind in ("open_bounty", "submit_candidate", "verify_accept", "close_deadline", "close_challenge_window"):
        state, _ = step(state, kind)
    _, result = step(state, "open_challenge")
    assert result["decision_kind"] == "reject"
    assert result["reason_code"] == "TIME_WINDOW"


def test_adapter_is_deterministic_and_owns_input() -> None:
    state = initial_abstract_state()
    document = doc(state, "open_bounty")
    first = step_document(document)
    document["state"]["phase"] = "canceled"
    second = step_document(doc(state, "open_bounty"))
    assert first == second


def test_json_line_process_is_strict_and_canonical() -> None:
    payload = canonical_json_bytes(doc(initial_abstract_state(), "open_bounty"))
    completed = subprocess.run(
        [sys.executable, "-m", "popperpad.esso_market_adapter"],
        input=payload,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
    )
    assert completed.returncode == 0, completed.stderr.decode()
    result = json.loads(completed.stdout)
    assert result["decision_kind"] == "accept"
    assert completed.stdout == canonical_json_bytes(result)

    noncanonical = b'{"schema":"popperpad/esso-market-step/v1", "abstraction_id":"x"}\n'
    rejected = subprocess.run(
        [sys.executable, "-m", "popperpad.esso_market_adapter"],
        input=noncanonical,
        capture_output=True,
        check=False,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
    )
    assert rejected.returncode != 0


def test_json_lines_process_reuses_one_strict_boundary() -> None:
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    process = subprocess.Popen(
        [sys.executable, "-m", "popperpad.esso_market_adapter", "--json-lines"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    state = initial_abstract_state()
    for kind in ("open_bounty", "submit_candidate"):
        process.stdin.write(canonical_json_bytes(doc(state, kind)))
        process.stdin.flush()
        line = process.stdout.readline()
        result = json.loads(line)
        assert line == canonical_json_bytes(result)
        state = AbstractMarketState.from_mapping(result["state"])
    process.stdin.close()
    assert process.wait(timeout=5) == 0
    assert process.stderr is not None
    assert process.stderr.read() == b""
    assert state.phase == "Open"
    assert state.submission == "Pending"


def test_abstract_constructor_rejects_unjustified_slashing() -> None:
    raw = json.loads(canonical_json_bytes(initial_abstract_state().as_json()))
    raw.update(
        {
            "phase": "Open",
            "escrow_atoms": 2,
            "submission": "Rejected",
            "bond_slashed_atoms": 1,
            "challenge": "None",
        }
    )
    with pytest.raises(ValueError, match="unjustified_bond_slash"):
        AbstractMarketState.from_mapping(raw)
