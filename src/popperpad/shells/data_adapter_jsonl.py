"""Strict bytes-boundary JSONL data adapter shell.

Reads one request per line from stdin (bytes), writes one response per line
to stdout (bytes). Uses strict canonical JSON parsing:

- Rejects duplicate object keys (at parse time via object_pairs_hook)
- Rejects trailing content after the JSON value
- Rejects non-UTF-8 input
- Rejects empty input
- Enforces canonical request bytes: received bytes must equal canonical
  JSON encoding of the parsed value (no alternate byte encodings accepted)
- Preserves caller-supplied wire headers (schema, protocol_version, binding_hash)
  — the shell does NOT replace or repair them
- All boundary failures return committed INVALID_INPUT responses

The shell never imports datetime, os, or other effectful modules for
parsing logic. It only uses sys.stdin/stdout for byte transport.
"""

from __future__ import annotations

import json
import sys
from typing import BinaryIO

from ..core.adapter_protocol import (
    ADAPTER_PROTOCOL_VERSION,
    REQUEST_SCHEMA,
    AdapterBinding,
    AdapterOperation,
    AdapterRequest,
    DataAdapterProfile,
    ExecutionContext,
    InvalidInput,
    InvalidInputCode,
    build_invalid_input_response,
)
from ..core.codec import canonical_json_bytes
from ..core.values import FrozenDict, JsonValue, freeze_json, thaw_json
from ..refinement.market_adapter import apply_data_adapter
from ..refinement.profiles.market_single_slot_v1 import load_profile, load_binding


_ZERO_HASH = "sha256:" + "0" * 64


class StrictJSONParseError(Exception):
    """Raised when input bytes are not strict canonical JSON."""


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """object_pairs_hook that rejects duplicate keys at parse time."""

    seen: set[str] = set()
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in seen:
            raise StrictJSONParseError(f"duplicate key {key!r}")
        seen.add(key)
        result[key] = value
    return result


def parse_canonical_json(data: bytes) -> object:
    """Parse bytes as strict canonical JSON.

    Rejects:
    - Non-UTF-8 bytes
    - Trailing content after the JSON value
    - Duplicate object keys (detected at parse time via object_pairs_hook)
    - Non-canonical byte encodings (received bytes must equal canonical
      JSON encoding of the parsed value)
    """

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StrictJSONParseError(f"non-utf-8 input: {exc}") from exc
    raw = data.strip()
    if not raw:
        raise StrictJSONParseError("empty input")
    decoder = json.JSONDecoder(object_pairs_hook=_reject_duplicate_pairs)
    try:
        value, end = decoder.raw_decode(text)
    except StrictJSONParseError:
        raise
    except json.JSONDecodeError as exc:
        raise StrictJSONParseError(f"invalid json: {exc}") from exc
    if text[end:].strip():
        raise StrictJSONParseError("trailing content after json value")
    # Enforce canonical bytes: received bytes must equal canonical encoding.
    # The canonical_json_bytes function appends a trailing newline for file
    # storage; in JSONL the newline is the line delimiter, not content, so
    # we compare against the canonical form without the trailing newline.
    canonical = canonical_json_bytes(value).rstrip(b"\n")
    if raw != canonical:
        raise StrictJSONParseError("input is not canonical JSON (byte encoding differs from canonical form)")
    return value


def serialize_json(value: object) -> bytes:
    """Serialize a value as canonical JSON bytes (without trailing newline)."""

    plain = thaw_json(value) if isinstance(value, (FrozenDict, tuple)) else value
    encoded = json.dumps(plain, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return encoded.encode("utf-8")


def process_line(
    line: bytes,
    profile: DataAdapterProfile,
    binding: AdapterBinding,
) -> bytes:
    """Process one JSONL line and return the response bytes."""

    try:
        raw = parse_canonical_json(line)
    except StrictJSONParseError as exc:
        return _invalid_input_bytes(binding, "$", str(exc))

    if not isinstance(raw, dict):
        return _invalid_input_bytes(binding, "$", "request must be a JSON object")

    try:
        frozen = freeze_json(raw)
    except (TypeError, ValueError) as exc:
        return _invalid_input_bytes(binding, "$", str(exc))
    if not isinstance(frozen, FrozenDict):
        return _invalid_input_bytes(binding, "$", "request must be a JSON object")

    try:
        request = _build_request(frozen)
    except (ValueError, TypeError, KeyError) as exc:
        return _invalid_input_bytes(binding, "$", str(exc))

    response = apply_data_adapter(profile, binding, request)
    return serialize_json(response.as_json())


def _build_request(frozen: FrozenDict[JsonValue]) -> AdapterRequest:
    """Construct a typed AdapterRequest from parsed JSON.

    Preserves caller-supplied wire headers — does NOT replace schema,
    protocol_version, or binding_hash with local values.
    """

    request_id = frozen.get("request_id")
    case_id = frozen.get("case_id")
    if type(request_id) is not str or not request_id:
        raise ValueError("request_id must be a non-empty string")
    if type(case_id) is not str or not case_id:
        raise ValueError("case_id must be a non-empty string")

    schema = frozen.get("schema")
    if type(schema) is not str:
        raise ValueError("schema must be a string")
    if schema != REQUEST_SCHEMA:
        raise ValueError(f"schema must be {REQUEST_SCHEMA}, got {schema!r}")

    protocol_version = frozen.get("protocol_version")
    if type(protocol_version) is not str:
        raise ValueError("protocol_version must be a string")
    if protocol_version != ADAPTER_PROTOCOL_VERSION:
        raise ValueError(f"protocol_version must be {ADAPTER_PROTOCOL_VERSION}, got {protocol_version!r}")

    binding_hash = frozen.get("binding_hash")
    if type(binding_hash) is not str:
        raise ValueError("binding_hash must be a string")

    operation_raw = frozen.get("operation")
    if type(operation_raw) is not str:
        raise ValueError("operation must be a string")
    operation = AdapterOperation(operation_raw)

    state_raw = frozen.get("state")
    if not isinstance(state_raw, FrozenDict):
        raise ValueError("state must be a JSON object")

    command_raw = frozen.get("command")
    if command_raw is not None and not isinstance(command_raw, FrozenDict):
        raise ValueError("command must be null or a JSON object")

    ctx_raw = frozen.get("execution_context")
    if not isinstance(ctx_raw, FrozenDict):
        raise ValueError("execution_context must be a JSON object")
    time_class = ctx_raw.get("time_class")
    now_epoch_s = ctx_raw.get("now_epoch_s")
    if type(time_class) is not str:
        raise ValueError("execution_context.time_class must be a string")
    if type(now_epoch_s) is not int or isinstance(now_epoch_s, bool):
        raise ValueError("execution_context.now_epoch_s must be an integer")
    ctx = ExecutionContext(time_class=time_class, now_epoch_s=now_epoch_s)

    expected_hash = frozen.get("expected_pre_state_hash", _ZERO_HASH)

    return AdapterRequest(
        schema=schema,
        protocol_version=protocol_version,
        request_id=request_id,
        case_id=case_id,
        binding_hash=binding_hash,
        operation=operation,
        state=state_raw,
        command=command_raw,
        execution_context=ctx,
        expected_pre_state_hash=expected_hash,
    )


def _invalid_input_bytes(binding: AdapterBinding, field_path: str, detail: str) -> bytes:
    """Build an INVALID_INPUT response for boundary parse failures.

    Uses the caller-supplied binding_hash from the failed request when
    available, falling back to a boundary-failure request.
    """

    dummy = AdapterRequest(
        schema=REQUEST_SCHEMA,
        protocol_version=ADAPTER_PROTOCOL_VERSION,
        request_id="boundary-failure",
        case_id="boundary-failure",
        binding_hash=binding.hash(),
        operation=AdapterOperation.VALIDATE_STATE,
        state=FrozenDict(),
        command=None,
        execution_context=ExecutionContext(time_class="pre_deadline", now_epoch_s=0),
        expected_pre_state_hash=_ZERO_HASH,
    )
    response = build_invalid_input_response(
        request=dummy,
        invalid=InvalidInput(
            code=InvalidInputCode.NON_CANONICAL_JSON,
            field_path=field_path,
            detail=detail,
        ),
        pre_state=FrozenDict(),
        pre_state_hash=_ZERO_HASH,
    )
    return serialize_json(response.as_json())


def run_jsonl_shell(stdin: BinaryIO, stdout: BinaryIO) -> None:
    """Run the JSONL shell: read lines from stdin, write responses to stdout."""

    profile = load_profile()
    binding = load_binding(profile)
    for line in stdin:
        line = line.rstrip(b"\n\r")
        if not line:
            continue
        response_bytes = process_line(line, profile, binding)
        stdout.write(response_bytes)
        stdout.write(b"\n")
        stdout.flush()
