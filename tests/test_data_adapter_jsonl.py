"""Tests for the strict bytes-boundary JSONL shell.

Tests verify:
- Strict canonical JSON parsing: duplicate keys, trailing content, non-UTF-8,
  non-canonical byte encodings all rejected.
- Boundary failures return committed INVALID_INPUT responses.
- Valid requests are processed correctly.
- Caller-supplied wire headers (schema, protocol_version, binding_hash)
  are preserved, not replaced.
- Floats where integers are expected are rejected.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from popperpad.shells.data_adapter_jsonl import (
    MAX_REQUEST_BYTES,
    StrictJSONParseError,
    parse_canonical_json,
    process_line,
    run_jsonl_shell,
)
from popperpad.refinement.profiles.market_single_slot_v1 import load_profile, load_binding
from popperpad.refinement.finite_state import initial_abstract_state
from popperpad.refinement.market_adapter import abstract_state_hash
from popperpad.core.adapter_protocol import (
    ADAPTER_PROTOCOL_VERSION,
    BOUNDARY_RESPONSE_SCHEMA,
    REQUEST_SCHEMA,
)
from popperpad.core.codec import sha256_bytes


@pytest.fixture
def profile():
    return load_profile()


@pytest.fixture
def binding(profile):
    return load_binding(profile)


def _canonical_request_dict(**overrides) -> dict:
    """Build a canonical request dict with required wire headers."""

    initial = initial_abstract_state()
    base = {
        "binding_hash": overrides.pop("binding_hash", None),
        "case_id": "c1",
        "command": None,
        "execution_context": {"now_epoch_s": 100, "time_class": "pre_deadline"},
        "expected_pre_state_hash": overrides.pop("expected_pre_state_hash", abstract_state_hash(initial)),
        "operation": "validate_state",
        "protocol_version": ADAPTER_PROTOCOL_VERSION,
        "request_id": "r1",
        "schema": REQUEST_SCHEMA,
        "state": {
            "bond_atoms": 0,
            "challenge_opened_time_class": "none",
            "challenge_receipt_ref": None,
            "challenge_status": "none",
            "deposit_atoms": 0,
            "escrow_atoms": 0,
            "payable": False,
            "phase": "draft",
            "processed_command_mask": 0,
            "settled": False,
            "submission_receipt_ref": None,
            "submission_status": "none",
            "submission_time_class": "none",
        },
    }
    base.update(overrides)
    return base


def _canonical_bytes(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------------------
# Strict canonical JSON parsing tests.
# ---------------------------------------------------------------------------

def test_parse_rejects_duplicate_keys() -> None:
    with pytest.raises(StrictJSONParseError, match="duplicate"):
        parse_canonical_json(b'{"a":1,"a":2}')


def test_parse_rejects_nested_duplicate_keys() -> None:
    with pytest.raises(StrictJSONParseError, match="duplicate"):
        parse_canonical_json(b'{"outer":{"inner":1,"inner":2}}')


def test_parse_rejects_trailing_content() -> None:
    with pytest.raises(StrictJSONParseError, match="trailing"):
        parse_canonical_json(b'{"a":1} garbage')


def test_parse_rejects_non_utf8() -> None:
    with pytest.raises(StrictJSONParseError, match="utf") as exc_info:
        parse_canonical_json(b'{"a":1}\xff\xfe')
    assert exc_info.value.code.value == "invalid_utf8"


def test_parse_rejects_empty_input() -> None:
    with pytest.raises(StrictJSONParseError, match="empty"):
        parse_canonical_json(b'')


def test_parse_rejects_invalid_json() -> None:
    with pytest.raises(StrictJSONParseError):
        parse_canonical_json(b'not json at all')


def test_parse_rejects_non_canonical_byte_encoding() -> None:
    """Whitespace inside JSON is not canonical — must reject."""
    with pytest.raises(StrictJSONParseError, match="canonical"):
        parse_canonical_json(b'{ "a" : 1 }')


def test_parse_rejects_non_canonical_key_order() -> None:
    """Keys not in sorted order is non-canonical — must reject."""
    with pytest.raises(StrictJSONParseError, match="canonical"):
        parse_canonical_json(b'{"b":2,"a":1}')


@pytest.mark.parametrize("value", [b'{"a":1.5}', b'{"a":NaN}', b'{"a":Infinity}'])
def test_parse_rejects_float_and_non_finite_json_with_typed_error(value: bytes) -> None:
    with pytest.raises(StrictJSONParseError) as exc_info:
        parse_canonical_json(value)
    assert exc_info.value.code.value == "float_not_allowed"


def test_parse_accepts_canonical_json() -> None:
    # Keys must be sorted, no whitespace, no trailing newline (that's the line delimiter)
    result = parse_canonical_json(b'{"a":1,"b":[1,2,3]}')
    assert result == {"a": 1, "b": [1, 2, 3]}


# ---------------------------------------------------------------------------
# Boundary failure → INVALID_INPUT tests.
# ---------------------------------------------------------------------------

def test_invalid_json_returns_invalid_input(profile, binding) -> None:
    resp = process_line(b'not json', profile, binding)
    parsed = json.loads(resp)
    assert parsed["schema"] == BOUNDARY_RESPONSE_SCHEMA
    assert parsed["decision_kind"] == "invalid_input"
    assert parsed["reason_code"] == "non_canonical_json"
    assert parsed["input_bytes_hash"] == sha256_bytes(b"not json")
    assert "request_id" not in parsed
    assert "request_hash" not in parsed


def test_duplicate_keys_returns_invalid_input(profile, binding) -> None:
    resp = process_line(b'{"a":1,"a":2}', profile, binding)
    parsed = json.loads(resp)
    assert parsed["decision_kind"] == "invalid_input"
    assert parsed["reason_code"] == "duplicate_json_key"


def test_non_canonical_bytes_returns_invalid_input(profile, binding) -> None:
    resp = process_line(b'{ "a" : 1 }', profile, binding)
    parsed = json.loads(resp)
    assert parsed["decision_kind"] == "invalid_input"
    assert parsed["reason_code"] == "non_canonical_json"


def test_non_utf8_returns_distinct_invalid_input_code(profile, binding) -> None:
    raw = b'{"a":1}\xff'
    parsed = json.loads(process_line(raw, profile, binding))
    assert parsed["reason_code"] == "invalid_utf8"
    assert parsed["input_bytes_hash"] == sha256_bytes(raw)


def test_float_returns_distinct_invalid_input_code(profile, binding) -> None:
    raw = b'{"a":1.5}'
    parsed = json.loads(process_line(raw, profile, binding))
    assert parsed["reason_code"] == "float_not_allowed"
    assert parsed["input_bytes_hash"] == sha256_bytes(raw)


def test_non_object_request_returns_invalid_input(profile, binding) -> None:
    resp = process_line(b'[1,2,3]', profile, binding)
    parsed = json.loads(resp)
    assert parsed["decision_kind"] == "invalid_input"


def test_missing_request_id_returns_invalid_input(profile, binding) -> None:
    d = _canonical_request_dict()
    del d["request_id"]
    resp = process_line(_canonical_bytes(d), profile, binding)
    parsed = json.loads(resp)
    assert parsed["decision_kind"] == "invalid_input"


# ---------------------------------------------------------------------------
# Wire header preservation tests (defect 5).
# ---------------------------------------------------------------------------

def test_wrong_schema_returns_invalid_input(profile, binding) -> None:
    d = _canonical_request_dict(binding_hash=binding.hash(), schema="wrong/schema")
    resp = process_line(_canonical_bytes(d), profile, binding)
    parsed = json.loads(resp)
    assert parsed["decision_kind"] == "invalid_input"
    assert parsed["reason_code"] == "schema_mismatch"


def test_wrong_protocol_version_returns_invalid_input(profile, binding) -> None:
    d = _canonical_request_dict(binding_hash=binding.hash(), protocol_version="wrong")
    resp = process_line(_canonical_bytes(d), profile, binding)
    parsed = json.loads(resp)
    assert parsed["decision_kind"] == "invalid_input"
    assert parsed["reason_code"] == "schema_mismatch"


def test_wrong_binding_hash_returns_invalid_input(profile, binding) -> None:
    wrong_hash = "sha256:" + "b" * 64
    d = _canonical_request_dict(binding_hash=wrong_hash)
    resp = process_line(_canonical_bytes(d), profile, binding)
    parsed = json.loads(resp)
    assert parsed["decision_kind"] == "invalid_input"
    assert parsed["reason_code"] == "binding_mismatch"


def test_unknown_top_level_field_is_rejected_without_normalization(profile, binding) -> None:
    d = _canonical_request_dict(binding_hash=binding.hash(), extra="must-not-disappear")
    parsed = json.loads(process_line(_canonical_bytes(d), profile, binding))
    assert parsed["decision_kind"] == "invalid_input"
    assert parsed["reason_code"] == "unknown_field"


def test_unknown_execution_context_field_is_rejected(profile, binding) -> None:
    d = _canonical_request_dict(binding_hash=binding.hash())
    d["execution_context"]["clock_source"] = "host"
    parsed = json.loads(process_line(_canonical_bytes(d), profile, binding))
    assert parsed["decision_kind"] == "invalid_input"
    assert parsed["reason_code"] == "unknown_field"


def test_unknown_state_field_is_rejected(profile, binding) -> None:
    d = _canonical_request_dict(binding_hash=binding.hash())
    d["state"]["paid"] = False
    parsed = json.loads(process_line(_canonical_bytes(d), profile, binding))
    assert parsed["decision_kind"] == "invalid_input"
    assert parsed["reason_code"] == "abstract_state_out_of_domain"


def test_unknown_command_field_is_rejected(profile, binding) -> None:
    initial = initial_abstract_state()
    d = _canonical_request_dict(
        binding_hash=binding.hash(),
        operation="step",
        command={"kind": "open_bounty", "accepted": None},
        expected_pre_state_hash=abstract_state_hash(initial),
    )
    parsed = json.loads(process_line(_canonical_bytes(d), profile, binding))
    assert parsed["decision_kind"] == "invalid_input"
    assert parsed["reason_code"] == "abstract_command_out_of_domain"


def test_oversized_request_is_rejected_and_bound_to_input_hash(profile, binding) -> None:
    raw = b"x" * (MAX_REQUEST_BYTES + 1)
    parsed = json.loads(process_line(raw, profile, binding))
    assert parsed["decision_kind"] == "invalid_input"
    assert parsed["reason_code"] == "input_too_large"
    assert parsed["input_bytes_hash"] == sha256_bytes(raw)


def test_validate_state_with_command_returns_typed_boundary_failure(profile, binding) -> None:
    d = _canonical_request_dict(
        binding_hash=binding.hash(),
        command={"kind": "open_bounty"},
    )
    parsed = json.loads(process_line(_canonical_bytes(d), profile, binding))
    assert parsed["schema"] == BOUNDARY_RESPONSE_SCHEMA
    assert parsed["reason_code"] == "abstract_command_out_of_domain"
    assert parsed["reason_details"]["field_path"] == "$.command"


# ---------------------------------------------------------------------------
# Valid request processing tests.
# ---------------------------------------------------------------------------

def test_valid_validate_state_request(profile, binding) -> None:
    d = _canonical_request_dict(binding_hash=binding.hash())
    resp = process_line(_canonical_bytes(d), profile, binding)
    parsed = json.loads(resp)
    assert parsed["decision_kind"] == "accept"


def test_valid_step_request(profile, binding) -> None:
    initial = initial_abstract_state()
    d = _canonical_request_dict(
        binding_hash=binding.hash(),
        operation="step",
        command={"kind": "open_bounty"},
        expected_pre_state_hash=abstract_state_hash(initial),
    )
    resp = process_line(_canonical_bytes(d), profile, binding)
    parsed = json.loads(resp)
    assert parsed["decision_kind"] == "accept"
    assert parsed["post_state"]["phase"] == "open"


# ---------------------------------------------------------------------------
# JSONL shell end-to-end test.
# ---------------------------------------------------------------------------

def test_run_jsonl_shell_processes_multiple_lines(profile, binding) -> None:
    valid = _canonical_request_dict(binding_hash=binding.hash())
    lines = [
        _canonical_bytes(valid).decode("utf-8"),
        "not valid json",
    ]
    stdin = io.BytesIO(("\n".join(lines) + "\n").encode("utf-8"))
    stdout = io.BytesIO()
    run_jsonl_shell(stdin, stdout)
    output = stdout.getvalue()
    responses = [json.loads(line) for line in output.strip().split(b"\n") if line]
    assert len(responses) == 2
    assert responses[0]["decision_kind"] == "accept"
    assert responses[1]["decision_kind"] == "invalid_input"


def test_module_entry_point_reads_stdin_and_writes_stdout() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repository_root / "src")

    completed = subprocess.run(
        [sys.executable, "-m", "popperpad.shells.data_adapter_jsonl"],
        input=b"not json\n",
        capture_output=True,
        check=False,
        cwd=repository_root,
        env=environment,
    )

    assert completed.returncode == 0
    response = json.loads(completed.stdout)
    assert response["decision_kind"] == "invalid_input"
    assert response["input_bytes_hash"] == sha256_bytes(b"not json")
    assert completed.stderr == b""


def test_run_jsonl_shell_recovers_after_integer_decoder_failure(profile, binding) -> None:
    oversized_integer = b"9" * 5_000
    valid = _canonical_bytes(_canonical_request_dict(binding_hash=binding.hash()))
    stdin = io.BytesIO(oversized_integer + b"\n" + valid + b"\n")
    stdout = io.BytesIO()

    run_jsonl_shell(stdin, stdout)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert len(responses) == 2
    assert responses[0]["decision_kind"] == "invalid_input"
    assert responses[0]["input_bytes_hash"] == sha256_bytes(oversized_integer)
    assert responses[1]["decision_kind"] == "accept"


def test_run_jsonl_shell_recovers_after_unencodable_string(profile, binding) -> None:
    invalid = b'{"x":"\\ud800"}'
    valid = _canonical_bytes(_canonical_request_dict(binding_hash=binding.hash()))
    stdin = io.BytesIO(invalid + b"\n" + valid + b"\n")
    stdout = io.BytesIO()

    run_jsonl_shell(stdin, stdout)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert len(responses) == 2
    assert responses[0]["reason_code"] == "non_canonical_json"
    assert responses[0]["input_bytes_hash"] == sha256_bytes(invalid)
    assert responses[1]["decision_kind"] == "accept"


def test_run_jsonl_shell_returns_boundary_failure_for_blank_record(profile, binding) -> None:
    stdin = io.BytesIO(b"\n")
    stdout = io.BytesIO()

    run_jsonl_shell(stdin, stdout)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert len(responses) == 1
    assert responses[0]["schema"] == BOUNDARY_RESPONSE_SCHEMA
    assert responses[0]["reason_code"] == "non_canonical_json"
    assert responses[0]["input_bytes_hash"] == sha256_bytes(b"")


def test_run_jsonl_shell_drains_oversized_line_and_recovers(profile, binding) -> None:
    valid = _canonical_bytes(_canonical_request_dict(binding_hash=binding.hash()))
    oversized = b"x" * (MAX_REQUEST_BYTES + 100)
    stdin = io.BytesIO(oversized + b"\n" + valid + b"\n")
    stdout = io.BytesIO()
    run_jsonl_shell(stdin, stdout)
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [response["reason_code"] for response in responses] == [
        "input_too_large",
        None,
    ]
    assert responses[0]["input_bytes_hash"] == sha256_bytes(oversized)
    assert responses[1]["decision_kind"] == "accept"


def test_run_jsonl_shell_drains_cr_at_chunk_boundary_as_one_record(profile, binding) -> None:
    valid = _canonical_bytes(_canonical_request_dict(binding_hash=binding.hash()))
    payload = b"x" * (MAX_REQUEST_BYTES + 1) + b"\r" + valid
    stdin = io.BytesIO(payload + b"\n")
    stdout = io.BytesIO()

    run_jsonl_shell(stdin, stdout)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert len(responses) == 1
    assert responses[0]["reason_code"] == "input_too_large"
    assert responses[0]["input_bytes_hash"] == sha256_bytes(payload)


def test_run_jsonl_shell_excludes_split_crlf_from_oversized_hash(
    profile,
    binding,
) -> None:
    valid = _canonical_bytes(_canonical_request_dict(binding_hash=binding.hash()))
    payload = b"x" * (MAX_REQUEST_BYTES + 1)
    stdin = io.BytesIO(payload + b"\r\n" + valid + b"\n")
    stdout = io.BytesIO()

    run_jsonl_shell(stdin, stdout)

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert len(responses) == 2
    assert responses[0]["reason_code"] == "input_too_large"
    assert responses[0]["input_bytes_hash"] == sha256_bytes(payload)
    assert responses[1]["decision_kind"] == "accept"
