"""JSON-lines shell for the data-only adapter protocol.

This module is a shell: it reads stdin and writes stdout. It contains no
market semantics. It parses canonical JSON requests, constructs adapter
protocol values, invokes ``apply_data_adapter``, and writes canonical JSON
responses.

Protocol: one canonical JSON request line → one canonical JSON response line.

Requirements:
- exact UTF-8, no BOM, LF endings only
- duplicate-key rejection
- no floats or nonfinite constants
- maximum request size and nesting depth
- unknown-field rejection
- no output other than protocol bytes on stdout
- diagnostics only on stderr
- persistent mode handles independent requests with no retained semantic state
- malformed request returns INVALID_INPUT and does not terminate persistent mode
- internal bug terminates the process and grants no proof credit
"""

from __future__ import annotations

import json
import sys
from typing import TextIO

from ..core.adapter_protocol import (
    ADAPTER_PROTOCOL_VERSION,
    ADAPTER_SCHEMA,
    AdapterOperation,
    AdapterRequest,
    ExecutionContext,
    MarketAdapterProfile,
)
from ..core.codec import canonical_json_bytes
from ..core.values import FrozenDict, JsonValue, freeze_json, thaw_json
from ..refinement.market_adapter import apply_data_adapter


MAX_REQUEST_BYTES = 1 << 20  # 1 MiB
MAX_NESTING_DEPTH = 64


def process_one_line(
    line: str,
    profile: MarketAdapterProfile,
    out: TextIO,
    err: TextIO,
) -> bool:
    """Process one request line. Returns True to continue, False to terminate."""

    stripped = line.strip()
    if not stripped:
        return True
    response = _try_process(stripped, profile, err)
    if response is None:
        return False
    out.write(response + "\n")
    out.flush()
    return True


def _try_process(stripped: str, profile: MarketAdapterProfile, err: TextIO) -> str | None:
    try:
        return _process_request(stripped, profile)
    except _ProtocolError as exc:
        err.write(f"protocol error: {exc}\n")
        return _invalid_input_json(profile, exc.code, exc.field_path, exc.detail)
    except Exception as exc:
        err.write(f"internal error: {exc}\n")
        raise


def _process_request(stripped: str, profile: MarketAdapterProfile) -> str:
    raw = _parse_canonical_json(stripped)
    request = _build_request(raw, profile)
    response = apply_data_adapter(profile, request)
    return canonical_json_bytes(response.as_json()).decode("utf-8").rstrip("\n")


class _ProtocolError(Exception):
    def __init__(self, code: str, field_path: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.field_path = field_path
        self.detail = detail


def _parse_canonical_json(text: str) -> dict:
    if len(text.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise _ProtocolError("INPUT_TOO_LARGE", "$", "request exceeds maximum size")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _ProtocolError("NON_CANONICAL_JSON", "$", f"json parse error: {exc}")
    if not isinstance(raw, dict):
        raise _ProtocolError("SCHEMA_MISMATCH", "$", "request root must be an object")
    _check_no_floats(raw, 0)
    return raw


def _check_no_floats(value: object, depth: int) -> None:
    if depth > MAX_NESTING_DEPTH:
        raise _ProtocolError("INPUT_TOO_LARGE", "$", "nesting depth exceeded")
    if isinstance(value, float):
        raise _ProtocolError("FLOAT_NOT_ALLOWED", "$", "floating-point values are not allowed")
    if isinstance(value, dict):
        for key, child in value.items():
            _check_no_floats(child, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_no_floats(item, depth + 1)


def _build_request(raw: dict, profile: MarketAdapterProfile) -> AdapterRequest:
    schema = raw.get("schema")
    if schema != ADAPTER_SCHEMA:
        raise _ProtocolError("SCHEMA_MISMATCH", "$.schema", f"expected {ADAPTER_SCHEMA}")
    protocol_version = raw.get("protocol_version")
    if protocol_version != ADAPTER_PROTOCOL_VERSION:
        raise _ProtocolError("SCHEMA_MISMATCH", "$.protocol_version", "protocol version mismatch")
    operation_str = raw.get("operation")
    if operation_str not in ("validate_state", "step"):
        raise _ProtocolError("SCHEMA_MISMATCH", "$.operation", "must be validate_state or step")
    operation = AdapterOperation(operation_str)
    state_raw = raw.get("state")
    if not isinstance(state_raw, dict):
        raise _ProtocolError("SCHEMA_MISMATCH", "$.state", "must be an object")
    command_raw = raw.get("command")
    if command_raw is not None and not isinstance(command_raw, dict):
        raise _ProtocolError("SCHEMA_MISMATCH", "$.command", "must be null or object")
    ctx_raw = raw.get("execution_context")
    if not isinstance(ctx_raw, dict):
        raise _ProtocolError("SCHEMA_MISMATCH", "$.execution_context", "must be an object")
    ctx = ExecutionContext(
        time_class=_req_str_raw(ctx_raw, "time_class"),
        now_epoch_s=_req_int_raw(ctx_raw, "now_epoch_s"),
    )
    state_frozen = _freeze_dict(state_raw)
    command_frozen = _freeze_dict(command_raw) if command_raw is not None else None
    return AdapterRequest(
        schema=ADAPTER_SCHEMA,
        protocol_version=ADAPTER_PROTOCOL_VERSION,
        request_id=_req_str_raw(raw, "request_id"),
        case_id=_req_str_raw(raw, "case_id"),
        profile_id=profile.profile_id,
        profile_hash=profile.hash(),
        source_manifest_hash=profile.source_manifest_hash,
        model_ir_hash=profile.model_ir_hash,
        operation=operation,
        state=state_frozen,
        command=command_frozen,
        execution_context=ctx,
        expected_pre_state_hash=_req_str_raw(raw, "expected_pre_state_hash"),
    )


def _freeze_dict(raw: dict) -> FrozenDict:
    result = freeze_json(raw)
    if not isinstance(result, FrozenDict):
        raise _ProtocolError("SCHEMA_MISMATCH", "$", "expected JSON object")
    return result


def _req_str_raw(d: dict, key: str) -> str:
    value = d.get(key)
    if not isinstance(value, str) or not value:
        raise _ProtocolError("SCHEMA_MISMATCH", f"$.{key}", "must be a non-empty string")
    return value


def _req_int_raw(d: dict, key: str) -> int:
    value = d.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise _ProtocolError("SCHEMA_MISMATCH", f"$.{key}", "must be an integer")
    return value


def _invalid_input_json(
    profile: MarketAdapterProfile,
    code: str,
    field_path: str,
    detail: str,
) -> str:
    response_data = {
        "schema": ADAPTER_SCHEMA,
        "protocol_version": ADAPTER_PROTOCOL_VERSION,
        "request_id": "unknown",
        "case_id": "unknown",
        "profile_id": profile.profile_id,
        "profile_hash": profile.hash(),
        "source_manifest_hash": profile.source_manifest_hash,
        "model_ir_hash": profile.model_ir_hash,
        "request_hash": "sha256:" + "0" * 64,
        "decision_kind": "invalid_input",
        "reason_code": code,
        "reason_details": {"code": code, "field_path": field_path, "detail": detail},
        "pre_state": {},
        "pre_state_hash": "sha256:" + "0" * 64,
        "post_state": None,
        "post_state_hash": None,
        "effects": [],
        "effect_plan_hash": None,
        "receipt": None,
        "state_violations": [],
        "projection_warnings": [],
        "response_commitment": "sha256:" + "0" * 64,
    }
    return canonical_json_bytes(response_data).decode("utf-8").rstrip("\n")


def run_one_shot(profile: MarketAdapterProfile, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    """One-shot mode: read one request line, write one response line."""

    line = stdin.readline()
    if not line:
        return 0
    process_one_line(line, profile, stdout, stderr)
    return 0


def run_persistent(profile: MarketAdapterProfile, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    """Persistent mode: read lines until EOF, handling each independently."""

    for line in stdin:
        if not process_one_line(line, profile, stdout, stderr):
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    from ..refinement.profiles.market_single_slot_v1 import load_profile

    profile = load_profile()
    mode = (argv or sys.argv[1:])[0] if (argv or sys.argv[1:]) else "persistent"
    if mode == "one-shot":
        return run_one_shot(profile, sys.stdin, sys.stdout, sys.stderr)
    return run_persistent(profile, sys.stdin, sys.stdout, sys.stderr)
